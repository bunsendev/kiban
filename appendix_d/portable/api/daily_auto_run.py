"""Trace and resume the operator-confirmed daily Portable workflow."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from .business_review import review_view
from .decision_input_contracts import DecisionInputError
from .decision_input_guided import package_payload, requirements
from .formal_forecast_pipeline import PortableFormalForecastPipeline
from .formal_pipeline import PortableFormalPipeline
from .production_handoff import ProductionHandoffError


class DailyAutoRunError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


class PortableDailyAutoRun:
    """A durable read model over existing immutable workflow artifacts.

    Human business decisions remain in their owning ledgers.  This service only
    links those artifacts, records progress, and executes already-confirmed
    deterministic stages.
    """

    def __init__(self, paths, production_workflow) -> None:
        self.paths = paths
        self.root = paths.state / "DailyAutoRuns"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pipeline = PortableFormalPipeline(paths)
        self.forecast = PortableFormalForecastPipeline(paths)
        self.production = production_workflow

    def list(self) -> list[dict]:
        values = []
        for path in self.root.glob("*.json"):
            try:
                values.append(self._verified(path))
            except DailyAutoRunError:
                continue
        return sorted(values, key=lambda item: item["updated_at"], reverse=True)[:50]

    def view(self, analysis_id: str) -> dict:
        with self.lock:
            report = self._report(analysis_id)
            value = self._derive(report, self._bindings(analysis_id))
            return self._persist_if_changed(value)

    def advance(self, analysis_id: str, payload: dict) -> dict:
        with self.lock:
            return self._advance(analysis_id, payload)

    def prepare_decision(self, analysis_id: str, payload: dict) -> dict:
        with self.lock:
            current = self.view(analysis_id)
            if current["status"] not in {
                "SUMMARY_CONFIRMATION_REQUIRED",
                "DECISION_INPUT_REQUIRED",
                "DECISION_INPUT_BLOCKED",
            }:
                raise DailyAutoRunError("正式予測の完了後に日次サマリーを準備してください")
            try:
                summary = self.production.projection.daily_summary(
                    current["build_id"], payload
                )
            except ProductionHandoffError as exc:
                raise DailyAutoRunError(str(exc)) from exc
            bindings = self._bindings(analysis_id) | {
                "summary_key": summary["request_key"],
                "decision_input_package_id": None,
                "recommendation_key": None,
            }
            return self._persist_if_changed(
                self._derive(self._report(analysis_id), bindings)
            )

    def submit_decision_inputs(self, analysis_id: str, payload: dict) -> dict:
        with self.lock:
            current = self.view(analysis_id)
            if current["status"] not in {
                "DECISION_INPUT_REQUIRED", "DECISION_INPUT_BLOCKED"
            }:
                raise DailyAutoRunError("日次サマリー作成後に正式入力を確認してください")
            summary_key = current.get("summary_key")
            if not summary_key:
                raise DailyAutoRunError("日次サマリーが見つかりません")
            try:
                summary = self.production.projection.get_summary(summary_key)
                package = self.production.input_packages.create(
                    current["build_id"], summary, payload
                )
                bindings = self._bindings(analysis_id) | {
                    "summary_key": summary_key,
                    "decision_input_package_id": package["package_id"],
                    "recommendation_key": None,
                }
                if package["status"] == "READY":
                    recommendation = self.production.decision.create(
                        current["build_id"], summary_key,
                        {
                            "decision_input_package_id": package["package_id"],
                            "confirm_decision_inputs": True,
                        },
                    )
                    bindings["recommendation_key"] = recommendation["request_key"]
            except (DecisionInputError, ProductionHandoffError) as exc:
                raise DailyAutoRunError(str(exc)) from exc
            return self._persist_if_changed(
                self._derive(self._report(analysis_id), bindings)
            )

    def decision_requirements(self, analysis_id: str) -> dict:
        with self.lock:
            current = self.view(analysis_id)
            if current["status"] not in {
                "DECISION_INPUT_REQUIRED", "DECISION_INPUT_BLOCKED"
            } or not current.get("summary_key"):
                raise DailyAutoRunError("工場・配送条件を入力できる状態ではありません")
            summary = self.production.projection.get_summary(current["summary_key"])
            return requirements(summary)

    def submit_guided_decision_inputs(self, analysis_id: str, payload: dict) -> dict:
        with self.lock:
            current = self.view(analysis_id)
            if current["status"] not in {
                "DECISION_INPUT_REQUIRED", "DECISION_INPUT_BLOCKED"
            } or not current.get("summary_key"):
                raise DailyAutoRunError("工場・配送条件を入力できる状態ではありません")
            summary = self.production.projection.get_summary(current["summary_key"])
            try:
                guided = package_payload(summary, payload)
            except DecisionInputError as exc:
                raise DailyAutoRunError(str(exc)) from exc
            return self.submit_decision_inputs(analysis_id, {
                "actor": guided["actor"],
                "reason": guided["reason"],
                "confirm_decision_inputs": True,
                "archive_base64": base64.b64encode(guided["archive"]).decode("ascii"),
            })

    def _advance(self, analysis_id: str, payload: dict) -> dict:
        current = self.view(analysis_id)
        if current["status"] == "REVIEW_REQUIRED":
            raise DailyAutoRunError("JAN・賞味期限などの未確認項目を先に確定してください")
        if current["status"] == "INVENTORY_CONFIRMATION_REQUIRED":
            raise DailyAutoRunError("拠点、在庫基準時刻、数量単位を先に確認してください")
        if current["status"] == "INVENTORY_BLOCKED":
            raise DailyAutoRunError("正式在庫候補の隔離理由を解消してください")
        if current["status"] in {
            "SUMMARY_CONFIRMATION_REQUIRED",
            "DECISION_INPUT_REQUIRED",
            "DECISION_INPUT_BLOCKED",
            "DECISION_BLOCKED",
            "SHIPMENT_REVIEW_REQUIRED",
            "COMPLETED",
        }:
            return current
        actor = str(payload.get("actor") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        required = (
            payload.get("confirm_pilot_scope") is True
            and payload.get("confirm_quantity_reconciliation") is True
            and payload.get("confirm_identity_bridge") is True
            and payload.get("confirm_zero_policy") is True
        )
        if not actor or not reason or not required:
            raise DailyAutoRunError("確認者、理由、4つの確認項目をすべて確認してください")
        handoff_id = current.get("handoff_id")
        if not handoff_id:
            raise DailyAutoRunError("正式在庫候補が見つかりません")

        pipeline_view = self.pipeline.view(handoff_id)
        registration = pipeline_view.get("latest")
        if not pipeline_view["latest_covers_all"]:
            registration = None
        if registration is None:
            selections = []
            for location in pipeline_view["locations"]:
                jans = location["jans"]
                if len(jans) < pipeline_view["minimum_products_per_location"]:
                    raise DailyAutoRunError(
                        f"{location['source_center']}に対象商品がありません"
                    )
                selections.append({"source_center": location["source_center"], "jans": jans})
            registration = self.pipeline.register(handoff_id, {
                "actor": actor, "reason": reason, "confirm_pilot_scope": True,
                "selections": selections,
            })

        for job in registration["jobs"]:
            if job["status"] == "APPROVAL_REQUIRED":
                registration = self.pipeline.approve(
                    registration["registration_id"], job["job_id"],
                    {"actor": actor, "reason": reason,
                     "expected_revision": job["decision_revision"]},
                )
        if registration["status"] != "APPROVED":
            raise DailyAutoRunError("隔離0件・数量一致の正式在庫だけを予測へ進められます")

        forecast = self.forecast.run(registration["registration_id"], {
            "actor": actor,
            "reason": reason,
            "confirm_identity_bridge": True,
            "confirm_zero_policy": True,
            "batch_size": payload.get("batch_size", 100),
        })
        if forecast.get("status") == "BLOCKED":
            return self.view(analysis_id)
        try:
            self.production.enqueue(forecast["build_id"], {
                "actor": actor,
                "reason": reason,
                "confirm_production_queue": True,
            })
        except ProductionHandoffError as exc:
            raise DailyAutoRunError(str(exc)) from exc
        return self.view(analysis_id)

    def _derive(self, report: dict, bindings: dict) -> dict:
        analysis_id = report["analysis_id"]
        reviewed = review_view(report, self.paths.decisions / f"{analysis_id}.jsonl")
        base = {
            "format": "portable-daily-auto-run-v1",
            "run_id": analysis_id,
            "analysis_id": analysis_id,
            "input_sha256": report["input_sha256"],
            "pending_items": reviewed["review"]["pending_items"],
            "pending_rows": reviewed["review"]["pending_rows"],
            "handoff_id": None,
            "registration_id": None,
            "build_id": None,
            "production_run_id": None,
            "summary_key": bindings.get("summary_key"),
            "decision_input_package_id": bindings.get(
                "decision_input_package_id"
            ),
            "recommendation_key": bindings.get("recommendation_key"),
            "blockers": [],
        }
        if reviewed["review"]["pending_rows"]:
            return base | {"status": "REVIEW_REQUIRED", "next_action": "未確定データを確認"}
        handoffs = self._handoffs(analysis_id)
        if not handoffs:
            return base | {"status": "INVENTORY_CONFIRMATION_REQUIRED",
                           "next_action": "拠点・基準時刻・数量単位を確認"}
        handoff = handoffs[0]
        base["handoff_id"] = handoff["handoff_id"]
        if handoff["status"] != "READY_FOR_FORMAL_INTAKE":
            base["blockers"] = handoff.get("blockers", [])
            return base | {"status": "INVENTORY_BLOCKED", "next_action": "隔離理由を解消"}
        pipeline_view = self.pipeline.view(handoff["handoff_id"])
        registration = pipeline_view.get("latest")
        if not pipeline_view["latest_covers_all"]:
            registration = None
        if registration is None:
            return base | {"status": "READY_TO_ADVANCE", "next_action": "確認して予測まで実行"}
        base["registration_id"] = registration["registration_id"]
        if registration["status"] != "APPROVED":
            base["blockers"] = [
                {"source_center": job["source_center"], "status": job["status"]}
                for job in registration["jobs"] if job["status"] != "APPROVED"
            ]
            return base | {"status": "READY_TO_ADVANCE", "next_action": "数量照合を確認して再開"}
        latest = self.forecast.view(registration["registration_id"]).get("latest")
        if latest is None:
            return base | {"status": "READY_TO_ADVANCE", "next_action": "予測条件を確認して再開"}
        base["build_id"] = latest["build_id"]
        base["blockers"] = [
            {"jan": item["jan"], "source_center": item["source_center"],
             "reason_codes": item["blocking_reasons"],
             "observed_day_count": item.get("observed_day_count"),
             "confirmed_zero_day_count": item.get("confirmed_zero_day_count"),
             "train_start": item.get("train_start"), "train_end": item.get("train_end"),
             "inventory_snapshot_date": item.get("inventory_snapshot_date")}
            for item in latest.get("series", []) if item.get("blocking_reasons")
        ]
        base |= {
            "forecast_status": latest["status"],
            "eligible_series_count": latest["eligible_series_count"],
            "blocked_series_count": latest["blocked_series_count"],
        }
        if not latest.get("predictions"):
            return base | {
                "status": "FORECAST_BLOCKED",
                "next_action": "履歴・基準日の不足を確認",
            }
        try:
            production = self.production.current(latest["build_id"])
        except ProductionHandoffError as exc:
            base["blockers"] = [{"code": "PRODUCTION_HANDOFF_INVALID", "detail": str(exc)}]
            return base | {
                "status": "PRODUCTION_BLOCKED",
                "next_action": "Production予測の受渡しを確認",
            }
        if not production["queued"]:
            return base | {
                "status": "PRODUCTION_CONFIRMATION_REQUIRED",
                "next_action": "確認してProduction予測へ登録",
            }
        handoff = production["handoff"]
        base["production_run_id"] = handoff["run_id"]
        if handoff["run_status"] in {"QUEUED", "RUNNING"}:
            return base | {
                "status": "PRODUCTION_RUNNING",
                "next_action": "Production予測の完了を待機",
            }
        if handoff["run_status"] != "SUCCEEDED":
            base["blockers"] = [{
                "code": f"PRODUCTION_{handoff['run_status']}",
                "detail": handoff.get("worker_error"),
            }]
            return base | {
                "status": "PRODUCTION_BLOCKED",
                "next_action": "Production予測の失敗理由を確認",
            }
        summary_key = bindings.get("summary_key")
        if not summary_key:
            return base | {
                "status": "SUMMARY_CONFIRMATION_REQUIRED",
                "next_action": "賞味期限条件を確認して日次サマリーを作成",
            }
        try:
            summary = self.production.projection.get_summary(summary_key)
            if summary["build_id"] != latest["build_id"]:
                raise ProductionHandoffError(
                    "日次サマリーと正式予測buildが一致しません"
                )
        except ProductionHandoffError as exc:
            base["blockers"] = [{"code": "DAILY_SUMMARY_INVALID", "detail": str(exc)}]
            return base | {
                "status": "DECISION_INPUT_BLOCKED",
                "next_action": "日次サマリーの整合性を確認",
            }
        base["summary_key"] = summary_key
        package_id = bindings.get("decision_input_package_id")
        if not package_id:
            return base | {
                "status": "DECISION_INPUT_REQUIRED",
                "next_action": "工場在庫・生産予定・route・安全在庫を入力",
            }
        try:
            package = self.production.input_packages.get(package_id)
        except DecisionInputError as exc:
            base["blockers"] = [{"code": "DECISION_INPUT_INVALID", "detail": str(exc)}]
            return base | {
                "status": "DECISION_INPUT_BLOCKED",
                "next_action": "正式Decision入力の整合性を確認",
            }
        base["decision_input_package_id"] = package_id
        base["decision_input_issue_count"] = (
            len(package["quarantines"]) + len(package["missing_or_outside_scope"])
        )
        if package["status"] != "READY":
            base["blockers"] = package["quarantines"] + package[
                "missing_or_outside_scope"
            ]
            return base | {
                "status": "DECISION_INPUT_BLOCKED",
                "next_action": "不足・隔離された正式入力を修正して再確認",
            }
        recommendation_key = bindings.get("recommendation_key")
        if not recommendation_key:
            return base | {
                "status": "DECISION_INPUT_REQUIRED",
                "next_action": "確認済み正式入力から推奨出荷を再開",
            }
        try:
            recommendation = self.production.decision.get(
                latest["build_id"], summary_key, recommendation_key
            )
        except ProductionHandoffError as exc:
            base["blockers"] = [{"code": "RECOMMENDATION_INVALID", "detail": str(exc)}]
            return base | {
                "status": "DECISION_BLOCKED",
                "next_action": "推奨出荷結果の整合性を確認",
            }
        base["recommendation_key"] = recommendation_key
        base["recommendation_count"] = len(recommendation["recommendations"])
        decision_blockers = recommendation["source_blockers"] + recommendation["blockers"]
        if decision_blockers or not recommendation["recommendations"]:
            base["blockers"] = decision_blockers or [{"code": "NO_RECOMMENDATIONS"}]
            return base | {
                "status": "DECISION_BLOCKED",
                "next_action": "推奨出荷の入力不足・計算対象外理由を確認",
            }
        reviews = self.production.reviews.view(recommendation)
        base["reviewed_recommendation_count"] = len(reviews["latest"])
        if len(reviews["latest"]) < len(recommendation["recommendations"]):
            return base | {
                "status": "SHIPMENT_REVIEW_REQUIRED",
                "next_action": "商品・倉庫ごとの推奨出荷を確認",
            }
        return base | {
            "status": "COMPLETED",
            "next_action": "本日の日次実行と担当者判断が完了",
        }

    def _bindings(self, analysis_id: str) -> dict:
        events = self._events(self.root / f"{analysis_id}.jsonl")
        latest = events[-1] if events else {}
        return {
            key: latest.get(key)
            for key in (
                "summary_key",
                "decision_input_package_id",
                "recommendation_key",
            )
        }

    def _persist_if_changed(self, value: dict) -> dict:
        target = self.root / f"{value['run_id']}.json"
        journal = self.root / f"{value['run_id']}.jsonl"
        events = self._events(journal)
        previous = events[-1] if events else None
        comparison = {key: item for key, item in value.items()
                      if key not in {"revision", "created_at", "updated_at", "record_sha256",
                                     "previous_record_sha256"}}
        old_comparison = None if previous is None else {
            key: item for key, item in previous.items()
            if key not in {"revision", "created_at", "updated_at", "record_sha256",
                           "previous_record_sha256"}
        }
        if comparison == old_comparison:
            return previous
        now = datetime.now(UTC).isoformat()
        record = value | {
            "revision": 1 if previous is None else previous["revision"] + 1,
            "created_at": now if previous is None else previous["created_at"],
            "updated_at": now,
            "previous_record_sha256": None if previous is None else previous["record_sha256"],
        }
        record["record_sha256"] = hashlib.sha256(_canonical(record)).hexdigest()
        with journal.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(record).decode("utf-8") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(_canonical(record))
        os.replace(temporary, target)
        return record

    def _verified(self, path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            events = self._events(path.with_suffix(".jsonl"))
            if not events or events[-1] != value:
                raise DailyAutoRunError("日次実行履歴の整合性を確認できません")
            return value
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise DailyAutoRunError("日次実行履歴を読み込めません") from exc

    def _events(self, path: Path) -> list[dict]:
        if not path.is_file():
            return []
        events = []
        previous_sha = None
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                value = json.loads(line)
                digest = value.pop("record_sha256")
                if value.get("previous_record_sha256") != previous_sha:
                    raise DailyAutoRunError("日次実行履歴の連鎖を確認できません")
                if hashlib.sha256(_canonical(value)).hexdigest() != digest:
                    raise DailyAutoRunError("日次実行履歴の整合性を確認できません")
                value["record_sha256"] = digest
                events.append(value)
                previous_sha = digest
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise DailyAutoRunError("日次実行履歴を読み込めません") from exc
        return events

    def _report(self, analysis_id: str) -> dict:
        if len(analysis_id) != 64 or any(c not in "0123456789abcdef" for c in analysis_id):
            raise DailyAutoRunError("分析結果が見つかりません")
        try:
            report = json.loads((self.paths.analysis / f"{analysis_id}.json").read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DailyAutoRunError("分析結果が見つかりません") from exc
        if report.get("analysis_id") != analysis_id:
            raise DailyAutoRunError("分析結果の整合性を確認できません")
        return report

    def _handoffs(self, analysis_id: str) -> list[dict]:
        values = []
        for path in self.paths.formal_inventory.glob("*/manifest.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("analysis_id") == analysis_id:
                values.append(value)
        return sorted(values, key=lambda item: item.get("created_at", ""), reverse=True)
