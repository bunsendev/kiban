"""検証済み証跡からAPI公開可能な固定項目だけを抽出する。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .contracts import BLOCKING_CHECKS, CHECK_IDS, FORMAT_VERSION, LIMITATIONS, OUTCOMES
from .evidence_schema import (
    HEX_SHA256,
    InvalidReportError,
    validate_checks,
    validate_conditions,
    validate_observations,
)
from .report import fingerprint

_TOP_LEVEL_KEYS = {
    "format_version",
    "dry_run_id",
    "checked_at",
    "conditions",
    "outcome",
    "checks",
    "observations",
    "limitations",
}


def _checked_at(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) > 40:
        raise InvalidReportError("実行日時が不正です")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidReportError("実行日時が不正です") from exc
    if parsed.utcoffset() is None:
        raise InvalidReportError("実行日時にtimezoneがありません")
    return value


def _derive_outcome(checks: list[dict[str, str]]) -> str:
    failed = {item["check_id"] for item in checks if item["status"] == "FAILED"}
    if failed & BLOCKING_CHECKS:
        return "BLOCKED"
    if "SAMPLE_ACCEPTANCE" in failed:
        return "REVIEW_REQUIRED"
    return "READY_FOR_NORMALIZATION"


def _validate_semantics(outcome, conditions, checks, observations) -> None:
    failed = [item["check_id"] for item in checks if item["status"] == "FAILED"]
    if len(failed) > 1:
        raise InvalidReportError("失敗判定が複数あります")
    if outcome != "BLOCKED":
        if {item["check_id"] for item in checks} != CHECK_IDS - {"CSV_STRUCTURE"}:
            raise InvalidReportError("完了判定の検査項目が不足しています")
        if not {"mapping_id", "source_sha256"} <= conditions.keys():
            raise InvalidReportError("完了判定の識別子が不足しています")
        if observations["sampled_rows"] < 1:
            raise InvalidReportError("完了判定のsampleが空です")
    if outcome == "READY_FOR_NORMALIZATION" and (
        failed or observations["quarantined_rows"] != 0
    ):
        raise InvalidReportError("合格判定と観測結果が一致しません")
    if outcome == "REVIEW_REQUIRED" and (
        failed != ["SAMPLE_ACCEPTANCE"] or observations["quarantined_rows"] < 1
    ):
        raise InvalidReportError("要確認判定と観測結果が一致しません")
    if outcome == "BLOCKED" and (not failed or failed[0] not in BLOCKING_CHECKS):
        raise InvalidReportError("停止判定と検査結果が一致しません")


def sanitize_report(payload: Any, report_sha256: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_KEYS:
        raise InvalidReportError("証跡schemaが不正です")
    if payload["format_version"] != FORMAT_VERSION:
        raise InvalidReportError("証跡versionが不正です")
    conditions = validate_conditions(payload["conditions"])
    dry_run_id = payload["dry_run_id"]
    if not isinstance(dry_run_id, str) or not HEX_SHA256.fullmatch(dry_run_id):
        raise InvalidReportError("ドライランIDが不正です")
    if dry_run_id != fingerprint(conditions):
        raise InvalidReportError("ドライランIDが条件と一致しません")
    checks = validate_checks(payload["checks"])
    outcome = payload["outcome"]
    if outcome not in OUTCOMES or outcome != _derive_outcome(checks):
        raise InvalidReportError("総合判定が不正です")
    if payload["limitations"] != list(LIMITATIONS):
        raise InvalidReportError("制約一覧が不正です")
    observations = validate_observations(payload["observations"])
    _validate_semantics(outcome, conditions, checks, observations)
    return {
        "report_sha256": report_sha256,
        "dry_run_id": dry_run_id,
        "checked_at": _checked_at(payload["checked_at"]),
        "outcome": outcome,
        "mapping_id": conditions.get("mapping_id"),
        "source_sha256": conditions.get("source_sha256"),
        "limits": dict(conditions["limits"]),
        "checks": checks,
        "observations": observations,
        "limitations": list(LIMITATIONS),
    }
