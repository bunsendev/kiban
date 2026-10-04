"""Immutable weekly evaluation grouped by the runtime actually used."""

from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

from forecast_provider.field_learning import (
    FieldMode,
    SqliteFieldLearningStore,
    build_actual_outcome_event,
    build_reference_case,
)

from .formal_shipment_daily import canonical_json, sha256
from .learning_reviews import PortableWeeklyLearningReviews
from .production_handoff import PortableProductionHandoff, ProductionHandoffError
from .runtime_weekly_metrics import (
    aggregate_runtime_group,
    pairwise_runtime_comparisons,
)

FORMAT = "portable-runtime-weekly-evaluation-v1"


class PortableRuntimeWeeklyEvaluations:
    """Join runtime evidence to weekly cases without rewriting either ledger."""

    def __init__(self, paths) -> None:
        self.paths = paths
        self.database = paths.state / "shipment-actual-outcomes.sqlite3"
        self.store = SqliteFieldLearningStore(self.database)
        self.weekly = PortableWeeklyLearningReviews(self.database)
        self.handoff = PortableProductionHandoff(paths)
        self.root = paths.state / "RuntimeWeeklyEvaluations"
        self.root.mkdir(parents=True, exist_ok=True)

    def overview(self) -> dict:
        evaluations = [
            _summary(self._verified(path))
            for path in sorted(self.root.glob("*.json"), reverse=True)
        ]
        weekly = self.weekly.overview()["reviews"]
        return {
            "mode": "SHADOW",
            "weekly_reviews": weekly,
            "evaluations": evaluations[:200],
            "notice": (
                "同じ週次版の取得済みActualだけでRuntime版を比較します。"
                "欠測は0へ変換せず、正式設定へ自動反映しません。"
            ),
        }

    def create(self, payload: dict) -> dict:
        review_id = _text(payload.get("weekly_review_id"), "週次集計版", 200)
        version = _text(payload.get("evaluation_version"), "Runtime評価版", 100)
        reviewer = _text(payload.get("reviewer"), "確認者", 100)
        if payload.get("confirm_same_actual_shadow") is not True:
            raise ProductionHandoffError(
                "同じ取得済みActualだけを使うSHADOW評価であることを確認してください"
            )
        weekly = self.weekly.view(review_id)
        report, evidence = self._build_report(weekly)
        body = {
            "format": FORMAT,
            "source_weekly_review_id": review_id,
            "source_weekly_review_sha256": weekly["content_sha256"],
            "evaluation_version": version,
            "reviewer": reviewer,
            "known_at": weekly["known_at"],
            "report": report,
            "evidence": evidence,
        }
        content_sha = sha256(canonical_json(body))
        evaluation_id = f"runtime-weekly-{content_sha}"
        target = self.root / f"{evaluation_id}.json"
        if target.is_file():
            return self._verified(target)
        value = {
            **body,
            "evaluation_id": evaluation_id,
            "recorded_at": datetime.now(UTC).isoformat(),
            "content_sha256": content_sha,
        }
        if not _atomic_new(target, canonical_json(value)):
            return self._verified(target)
        return value

    def view(self, evaluation_id: str) -> dict:
        if not evaluation_id.startswith("runtime-weekly-") or len(evaluation_id) != 79:
            raise ProductionHandoffError("Runtime週次評価が見つかりません")
        target = self.root / f"{evaluation_id}.json"
        if not target.is_file():
            raise ProductionHandoffError("Runtime週次評価が見つかりません")
        value = self._verified(target)
        weekly = self.weekly.view(value["source_weekly_review_id"])
        if weekly["content_sha256"] != value["source_weekly_review_sha256"]:
            raise ProductionHandoffError("元の週次集計版との整合性を確認できません")
        return value

    def _build_report(self, weekly: dict) -> tuple[dict, dict]:
        start = date.fromisoformat(weekly["week_start"])
        end = date.fromisoformat(weekly["week_end"])
        scopes = set(weekly["pilot_scope_versions"])
        cutoff = datetime.fromisoformat(weekly["known_at"]).astimezone(UTC)
        receipts = self._runtime_receipts(cutoff)
        groups: dict[tuple[str, str, str, str, str], list[dict]] = defaultdict(list)
        blockers: dict[str, list[str]] = defaultdict(list)
        evidence_cases = []
        cases = [
            case for case in _cases(self.store, start, end, scopes)
            if case.known_at <= cutoff
        ]
        expected_count = weekly["report"]["current"]["reference_case_count"]
        if len(cases) != expected_count:
            raise ProductionHandoffError("元の週次集計版と対象caseが一致しません")
        for case in cases:
            _verify_case(case)
            actual = _latest_before(self.store.list_actual_outcomes(case.case_id), cutoff)
            if actual is not None:
                _verify_actual(actual)
            decision = _latest_before(self.store.list_operator_decisions(case.case_id), cutoff)
            runtime = receipts.get(case.forecast_run_id)
            if runtime is None:
                blockers["RUNTIME_EVIDENCE_NOT_FOUND"].append(case.case_id)
                continue
            resolution = runtime["scopes"].get(case.pilot_scope_version)
            if resolution is None:
                blockers["SCOPE_RESOLUTION_NOT_FOUND"].append(case.case_id)
                continue
            signature = (
                runtime["runtime_version"], runtime["configuration_sha256"],
                runtime["provider_id"], runtime["model_name"], resolution["status"],
            )
            item = {"case": case, "actual": actual, "decision": decision, "runtime": runtime}
            groups[signature].append(item)
            evidence_cases.append({
                "case_id": case.case_id,
                "case_content_sha256": case.content_sha256,
                "actual_event_id": None if actual is None else actual.actual_event_id,
                "actual_content_sha256": None if actual is None else actual.content_sha256,
                "forecast_run_id": case.forecast_run_id,
                "runtime_receipt_sha256": runtime["receipt_sha256"],
                "runtime_resolution_id": resolution["resolution_id"],
            })
        runtime_groups = [
            aggregate_runtime_group(signature, items)
            for signature, items in sorted(groups.items(), key=lambda value: value[0])
        ]
        report = {
            "format": "portable-runtime-weekly-report-v1",
            "mode": "SHADOW",
            "week_start": weekly["week_start"],
            "week_end": weekly["week_end"],
            "pilot_scope_versions": sorted(scopes),
            "source_reference_case_count": weekly["report"]["current"][
                "reference_case_count"
            ],
            "attributed_case_count": sum(len(items) for items in groups.values()),
            "unattributed_case_count": sum(len(items) for items in blockers.values()),
            "runtime_groups": runtime_groups,
            "pairwise_comparisons": pairwise_runtime_comparisons(groups),
            "blockers": [
                {"code": code, "count": len(case_ids), "case_ids": sorted(case_ids)}
                for code, case_ids in sorted(blockers.items())
            ],
            "notice": (
                "Runtime別KPIは観測結果であり因果効果ではありません。版間比較は同一の"
                "業務日・JAN・倉庫でActualが一致するcaseだけを使用します。"
            ),
        }
        evidence = {
            "cases": sorted(evidence_cases, key=lambda item: item["case_id"]),
            "runtime_receipts": sorted({
                item["runtime_receipt_sha256"] for item in evidence_cases
            }),
        }
        return report, evidence

    def _runtime_receipts(self, cutoff: datetime) -> dict[str, dict]:
        result = {}
        for path in sorted(self.handoff.receipt_root.glob("*.json")):
            receipt = self.handoff._verified_receipt(path)
            required = {
                "run_id", "runtime_version", "runtime_configuration_sha256",
                "provider_id", "model_name", "runtime_resolutions", "receipt_sha256",
            }
            if not required.issubset(receipt):
                continue
            if not isinstance(receipt["runtime_resolutions"], list):
                continue
            scopes = {}
            valid = True
            for item in receipt["runtime_resolutions"]:
                if not isinstance(item, dict):
                    valid = False
                    break
                stored = self.store.get_runtime_assignment_resolution(
                    str(item.get("resolution_id") or "")
                )
                if (
                    stored is None
                    or stored.content_sha256 != item.get("content_sha256")
                    or stored.execution_key != receipt.get("build_id")
                    or stored.selected_version != receipt["runtime_version"]
                    or sha256(canonical_json(stored.selected_configuration))
                    != receipt["runtime_configuration_sha256"]
                    or stored.known_at > cutoff
                ):
                    valid = False
                    break
                if stored.pilot_scope_version in scopes:
                    valid = False
                    break
                scopes[stored.pilot_scope_version] = {
                    "resolution_id": stored.resolution_id,
                    "status": stored.status.value,
                }
            if not valid or not scopes or receipt["run_id"] in result:
                continue
            result[receipt["run_id"]] = {
                "runtime_version": receipt["runtime_version"],
                "configuration_sha256": receipt["runtime_configuration_sha256"],
                "provider_id": receipt["provider_id"],
                "model_name": receipt["model_name"],
                "receipt_sha256": receipt["receipt_sha256"],
                "scopes": scopes,
            }
        return result

    @staticmethod
    def _verified(path: Path) -> dict:
        try:
            value = json.loads(path.read_bytes())
            expected = value["content_sha256"]
            evaluation_id = value["evaluation_id"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ProductionHandoffError("Runtime週次評価の整合性を確認できません") from exc
        body = {
            key: item for key, item in value.items()
            if key not in {"evaluation_id", "recorded_at", "content_sha256"}
        }
        actual = sha256(canonical_json(body))
        if (
            value.get("format") != FORMAT
            or actual != expected
            or evaluation_id != f"runtime-weekly-{actual}"
        ):
            raise ProductionHandoffError("Runtime週次評価の整合性を確認できません")
        return value


def _cases(store, start: date, end: date, scopes: set[str]):
    values = []
    after = None
    while True:
        page = store.list_reference_cases_page(
            start_date=start, end_date=end, after=after, limit=500
        )
        values.extend(item for item in page if item.pilot_scope_version in scopes)
        if len(page) < 500:
            return values
        after = (page[-1].business_date, page[-1].case_id)


def _latest_before(events, cutoff: datetime):
    values = [item for item in events if item.known_at <= cutoff]
    return values[-1] if values else None


def _verify_case(value) -> None:
    rebuilt = build_reference_case(
        business_date=value.business_date, jan=value.jan,
        canonical_product_id=value.canonical_product_id,
        warehouse_id=value.warehouse_id, forecast_center_id=value.forecast_center_id,
        forecast_run_id=value.forecast_run_id,
        inventory_snapshot_id=value.inventory_snapshot_id,
        pilot_scope_version=value.pilot_scope_version,
        identity_bridge_version=value.identity_bridge_version,
        system_forecast_quantity=value.system_forecast_quantity,
        system_reference_quantity=value.system_reference_quantity,
        policy_version=value.policy_version, mode=FieldMode(value.mode),
        known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if rebuilt.case_id != value.case_id or rebuilt.content_sha256 != value.content_sha256:
        raise ProductionHandoffError("予測・推奨caseの整合性を確認できません")


def _verify_actual(value) -> None:
    rebuilt = build_actual_outcome_event(
        case_id=value.case_id, expected_revision=value.revision - 1,
        source_version=value.source_version, source_sha256=value.source_sha256,
        actual_shipped_quantity=value.actual_shipped_quantity,
        actual_demand_quantity=value.actual_demand_quantity,
        stockout_quantity=value.stockout_quantity, expired_quantity=value.expired_quantity,
        interwarehouse_transfer_quantity=value.interwarehouse_transfer_quantity,
        known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if (
        rebuilt.actual_event_id != value.actual_event_id
        or rebuilt.content_sha256 != value.content_sha256
    ):
        raise ProductionHandoffError("後日実績の整合性を確認できません")


def _summary(value: dict) -> dict:
    report = value["report"]
    return {
        "evaluation_id": value["evaluation_id"],
        "source_weekly_review_id": value["source_weekly_review_id"],
        "evaluation_version": value["evaluation_version"],
        "reviewer": value["reviewer"],
        "week_start": report["week_start"],
        "week_end": report["week_end"],
        "runtime_group_count": len(report["runtime_groups"]),
        "attributed_case_count": report["attributed_case_count"],
        "unattributed_case_count": report["unattributed_case_count"],
    }


def _text(value, label: str, maximum: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise ProductionHandoffError(f"{label}は1〜{maximum}文字です")
    return result


def _atomic_new(path: Path, raw: bytes) -> bool:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(raw)
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)
