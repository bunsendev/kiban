"""Immutable Pilot evaluation assessments and append-only human decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .change_applications import PortableChangeApplications
from .formal_shipment_daily import canonical_json, sha256
from .learning_reviews import LearningReviewConflict
from .pilot_evaluation_policy import evaluate_pilot_policy
from .production_handoff import ProductionHandoffError
from .runtime_weekly_evaluations import PortableRuntimeWeeklyEvaluations, _atomic_new

FORMAT = "portable-pilot-evaluation-assessment-v1"
DECISION_FORMAT = "portable-pilot-evaluation-decision-v1"
DECISIONS = {
    "CONTINUE_PILOT",
    "PAUSE_PILOT",
    "REQUEST_ROLLBACK",
    "FORWARD_TO_ACCEPTANCE",
}


class PortablePilotEvaluationGates:
    def __init__(self, paths) -> None:
        self.paths = paths
        self.applications = PortableChangeApplications(
            paths.state / "shipment-actual-outcomes.sqlite3"
        )
        self.runtime = PortableRuntimeWeeklyEvaluations(paths)
        self.root = paths.state / "PilotEvaluationGates"
        # Keep decision paths short enough for field PCs where long-path support is
        # disabled. The full assessment id remains inside every signed record.
        self.decision_root = paths.state / "PilotEvaluationDecisions"
        self.root.mkdir(parents=True, exist_ok=True)
        self.decision_root.mkdir(parents=True, exist_ok=True)

    def overview(self) -> dict:
        applications = [
            item
            for item in self.applications.overview()["applications"]
            if item["state"] == "PILOT_ACTIVE"
        ]
        evaluations = self.runtime.overview()["evaluations"]
        assessments = [
            _summary(self._view_file(path))
            for path in sorted(self.root.glob("pilot-assessment-*.json"), reverse=True)
        ]
        return {
            "mode": "SHADOW",
            "applications": applications,
            "runtime_evaluations": evaluations,
            "assessments": assessments[:200],
            "notice": (
                "機械判定は担当者判断の根拠です。"
                "正式設定、受入、rollbackを自動実行しません。"
            ),
        }

    def create(self, payload: dict) -> dict:
        application_id = _text(payload.get("application_id"), "Pilot適用計画", 200)
        evaluation_id = _text(payload.get("runtime_evaluation_id"), "Runtime週次評価", 200)
        reviewer = _text(payload.get("reviewer"), "確認者", 100)
        if payload.get("confirm_advisory_only") is not True:
            raise ProductionHandoffError("人が判断するSHADOW Gateであることを確認してください")
        application = self.applications.view_application(application_id)
        if application["state"] != "PILOT_ACTIVE" or not application["source_approval_is_current"]:
            raise ProductionHandoffError("有効なPILOT_ACTIVE適用計画だけを評価できます")
        runtime = self.runtime.view(evaluation_id)
        policy = _policy(payload)
        scopes = application["application_scope"].get("pilot_scope_versions")
        if not isinstance(scopes, list) or not scopes:
            raise ProductionHandoffError("Pilot適用範囲を確認できません")
        report = evaluate_pilot_policy(
            runtime["report"],
            candidate_version=application["candidate_version"],
            pilot_scope_versions={str(item) for item in scopes},
            policy=policy,
        )
        latest_event = self._latest_application_event(application_id)
        body = {
            "format": FORMAT,
            "application_id": application_id,
            "application_content_sha256": application["content_sha256"],
            "application_revision": application["revision"],
            "application_event_sha256": latest_event.content_sha256,
            "runtime_evaluation_id": evaluation_id,
            "runtime_evaluation_sha256": runtime["content_sha256"],
            "policy": _json_policy(policy),
            "reviewer": reviewer,
            "known_at": runtime["known_at"],
            "report": report,
        }
        content_sha = sha256(canonical_json(body))
        assessment_id = f"pilot-assessment-{content_sha}"
        target = self.root / f"{assessment_id}.json"
        if not target.is_file():
            value = {
                **body,
                "assessment_id": assessment_id,
                "recorded_at": datetime.now(UTC).isoformat(),
                "content_sha256": content_sha,
            }
            _atomic_new(target, canonical_json(value))
        return self.view(assessment_id)

    def view(self, assessment_id: str) -> dict:
        target = self.root / f"{assessment_id}.json"
        if not target.is_file():
            raise ProductionHandoffError("Pilot評価Gateが見つかりません")
        value = self._view_file(target)
        runtime = self.runtime.view(value["runtime_evaluation_id"])
        if runtime["content_sha256"] != value["runtime_evaluation_sha256"]:
            raise ProductionHandoffError("Runtime週次評価との整合性を確認できません")
        self._pinned_application_event(value)
        decisions = self._decisions(assessment_id)
        return {
            **value,
            "revision": len(decisions),
            "decisions": decisions,
            "latest_decision": None if not decisions else decisions[-1]["decision"],
        }

    def decide(self, assessment_id: str, payload: dict) -> dict:
        assessment = self.view(assessment_id)
        application = self.applications.view_application(assessment["application_id"])
        if application["state"] != "PILOT_ACTIVE" or not application["source_approval_is_current"]:
            raise ProductionHandoffError("現在PILOT_ACTIVEの適用計画だけを判断できます")
        expected = payload.get("expected_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ProductionHandoffError("expected_revisionは0以上の整数です")
        if expected != assessment["revision"]:
            raise LearningReviewConflict("Pilot評価判断が更新されています。再読み込みしてください")
        decision = str(payload.get("decision") or "")
        if decision not in DECISIONS:
            raise ProductionHandoffError("Pilot評価判断を確認してください")
        if decision == "FORWARD_TO_ACCEPTANCE" and assessment["report"]["status"] != "PASSED":
            raise ProductionHandoffError("Gate合格前は正式採用審査へ送れません")
        if payload.get("confirm_no_automatic_action") is not True:
            raise ProductionHandoffError("自動反映しない判断記録であることを確認してください")
        previous = (
            assessment["decisions"][-1]["content_sha256"] if assessment["decisions"] else None
        )
        body = {
            "format": DECISION_FORMAT,
            "assessment_id": assessment_id,
            "revision": expected + 1,
            "expected_revision": expected,
            "previous_content_sha256": previous,
            "decision": decision,
            "actor": _text(payload.get("actor"), "判断者", 100),
            "reason": _text(payload.get("reason"), "判断理由", 500),
            "known_at": datetime.now(UTC).isoformat(),
        }
        content_sha = sha256(canonical_json(body))
        value = {
            **body,
            "decision_id": f"pilot-decision-{content_sha}",
            "content_sha256": content_sha,
        }
        prefix = _assessment_prefix(assessment_id)
        # Revision-only target makes the filesystem link the compare-and-swap.
        # Two writers for the same revision cannot both create a record.
        target = self.decision_root / f"{prefix}-{expected + 1:06d}.json"
        if not _atomic_new(target, canonical_json(value)):
            stored = self._verified_decision(target)
            if stored != value:
                raise LearningReviewConflict("Pilot評価判断が同時に更新されました")
        return self.view(assessment_id)

    def _view_file(self, path: Path) -> dict:
        try:
            value = json.loads(path.read_bytes())
            expected = value["content_sha256"]
            assessment_id = value["assessment_id"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ProductionHandoffError("Pilot評価Gateの整合性を確認できません") from exc
        body = {
            key: item
            for key, item in value.items()
            if key not in {"assessment_id", "recorded_at", "content_sha256"}
        }
        actual = sha256(canonical_json(body))
        if (
            value.get("format") != FORMAT
            or actual != expected
            or assessment_id != f"pilot-assessment-{actual}"
        ):
            raise ProductionHandoffError("Pilot評価Gateの整合性を確認できません")
        return value

    def _decisions(self, assessment_id: str) -> list[dict]:
        prefix = _assessment_prefix(assessment_id)
        values = [
            self._verified_decision(path)
            for path in sorted(self.decision_root.glob(f"{prefix}-*.json"))
        ]
        if any(value.get("assessment_id") != assessment_id for value in values):
            raise ProductionHandoffError("Pilot評価判断の参照整合性を確認できません")
        previous = None
        for index, value in enumerate(values, 1):
            if (
                value["revision"] != index
                or value["expected_revision"] != index - 1
                or value["previous_content_sha256"] != previous
            ):
                raise ProductionHandoffError("Pilot評価判断の履歴整合性を確認できません")
            previous = value["content_sha256"]
        return values

    @staticmethod
    def _verified_decision(path: Path) -> dict:
        try:
            value = json.loads(path.read_bytes())
            expected = value["content_sha256"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ProductionHandoffError("Pilot評価判断の整合性を確認できません") from exc
        body = {
            key: item for key, item in value.items() if key not in {"decision_id", "content_sha256"}
        }
        actual = sha256(canonical_json(body))
        if (
            value.get("format") != DECISION_FORMAT
            or actual != expected
            or value.get("decision_id") != f"pilot-decision-{actual}"
        ):
            raise ProductionHandoffError("Pilot評価判断の整合性を確認できません")
        return value

    def _latest_application_event(self, application_id: str):
        events = self.applications.store.list_change_application_events(application_id)
        if not events:
            raise ProductionHandoffError("Pilot開始Gateの証跡がありません")
        return events[-1]

    def _pinned_application_event(self, value: dict) -> None:
        application = self.applications.store.get_change_application(value["application_id"])
        if application is None or application.content_sha256 != value["application_content_sha256"]:
            raise ProductionHandoffError("Pilot適用計画との整合性を確認できません")
        events = self.applications.store.list_change_application_events(value["application_id"])
        matched = [item for item in events if item.revision == value["application_revision"]]
        if len(matched) != 1 or matched[0].content_sha256 != value["application_event_sha256"]:
            raise ProductionHandoffError("Pilot開始Gate履歴との整合性を確認できません")


def _policy(payload: dict) -> dict:
    result = {
        "policy_version": _text(payload.get("policy_version"), "評価基準版", 100),
        "minimum_observation_days": _integer(
            payload.get("minimum_observation_days"), "最小観測日数", 1, 365
        ),
        "minimum_same_actual_count": _integer(
            payload.get("minimum_same_actual_count"), "最小共通Actual件数", 1, 1_000_000
        ),
    }
    for key, label in (
        ("maximum_unattributed_ratio", "Runtime未特定率上限"),
        ("maximum_mae_delta_cases", "MAE差上限"),
        ("maximum_wape_delta", "WAPE差上限"),
        ("maximum_operator_change_ratio", "担当者修正率上限"),
        ("maximum_stockout_cases", "欠品数量上限"),
        ("maximum_expired_cases", "期限切れ数量上限"),
        ("maximum_interwarehouse_transfer_cases", "倉庫間移動数量上限"),
    ):
        result[key] = _number(payload.get(key), label)
    for key in ("maximum_unattributed_ratio", "maximum_operator_change_ratio"):
        if not Decimal(0) <= result[key] <= Decimal(1):
            raise ProductionHandoffError(f"{key}は0〜1です")
    for key in (
        "maximum_stockout_cases",
        "maximum_expired_cases",
        "maximum_interwarehouse_transfer_cases",
    ):
        if result[key] < Decimal(0):
            raise ProductionHandoffError(f"{key}は0以上です")
    return result


def _json_policy(policy: dict) -> dict:
    return {
        key: (str(value) if isinstance(value, Decimal) else value) for key, value in policy.items()
    }


def _number(value, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProductionHandoffError(f"{label}は数値です") from exc
    if not result.is_finite():
        raise ProductionHandoffError(f"{label}は有限数です")
    return result


def _integer(value, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ProductionHandoffError(f"{label}は{minimum}〜{maximum}の整数です")
    return value


def _text(value, label: str, maximum: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise ProductionHandoffError(f"{label}は1〜{maximum}文字です")
    return result


def _summary(value: dict) -> dict:
    return {
        "assessment_id": value["assessment_id"],
        "application_id": value["application_id"],
        "runtime_evaluation_id": value["runtime_evaluation_id"],
        "policy_version": value["policy"]["policy_version"],
        "status": value["report"]["status"],
        "reviewer": value["reviewer"],
        "recorded_at": value["recorded_at"],
    }


def _assessment_prefix(assessment_id: str) -> str:
    prefix = "pilot-assessment-"
    digest = assessment_id.removeprefix(prefix)
    if not assessment_id.startswith(prefix) or len(digest) != 64:
        raise ProductionHandoffError("Pilot評価Gate IDを確認できません")
    return digest[:16]
