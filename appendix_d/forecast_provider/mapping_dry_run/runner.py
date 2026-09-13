"""mappingドライランの入力・sample判定・証跡保存を統合する。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .contracts import (
    BLOCKING_CHECKS,
    DEFAULT_LIMITS,
    FORMAT_VERSION,
    SUITE_ID,
    DryRunLimits,
    InputFailure,
    check,
)
from .inspector import inspect_sample
from .loader import load_mapping, load_source
from .report import fingerprint, publish_report


def _outcome(checks: list[dict]) -> str:
    failed = {item["check_id"] for item in checks if item["status"] == "FAILED"}
    if failed & BLOCKING_CHECKS:
        return "BLOCKED"
    if "SAMPLE_ACCEPTANCE" in failed:
        return "REVIEW_REQUIRED"
    return "READY_FOR_NORMALIZATION"


def collect_dry_run(
    input_root: Path,
    relative_source: str,
    mapping_file: Path,
    limits: DryRunLimits = DEFAULT_LIMITS,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    checks: list[dict] = []
    conditions = {"suite_id": SUITE_ID, "limits": limits.as_dict()}
    try:
        mapping = load_mapping(mapping_file, limits)
        checks.append(check("MAPPING_CONTRACT", True, True, True))
        conditions["mapping_id"] = mapping.mapping_id
        source = load_source(input_root, relative_source, limits)
        checks.extend(
            [
                check("SOURCE_PATH_SAFE", True, True, True),
                check(
                    "SOURCE_SIZE_LIMIT",
                    True,
                    source.size_bytes,
                    {"maximum": limits.max_source_bytes},
                ),
                check("SOURCE_ENCODING", True, source.encoding, ["utf-8-sig", "utf-8", "cp932"]),
            ]
        )
        conditions["source_sha256"] = source.sha256
        inspection = inspect_sample(source, mapping.definition, limits.sample_rows)
        checks.extend(
            [
                check("HEADER_UNIQUE", True, True, True),
                check("REQUIRED_COLUMNS", True, True, True),
                check("SAMPLE_ROWS", True, inspection.sampled_rows, {"minimum": 1}),
                check(
                    "SAMPLE_ACCEPTANCE",
                    inspection.quarantined_rows == 0,
                    {
                        "accepted_rows": inspection.accepted_rows,
                        "quarantined_rows": inspection.quarantined_rows,
                    },
                    {"quarantined_rows": 0},
                ),
                check(
                    "QUANTITY_RECONCILIATION",
                    inspection.quantity_reconciled,
                    inspection.quantity_reconciled,
                    True,
                ),
            ]
        )
        observations = {
            "sampled_rows": inspection.sampled_rows,
            "accepted_rows": inspection.accepted_rows,
            "quarantined_rows": inspection.quarantined_rows,
            "truncated": inspection.truncated,
            "quarantine_reason_counts": inspection.reason_counts,
        }
    except InputFailure as exc:
        checks.append(check(exc.check_id, False, False, True))
        observations = {}
    checked_at = now().astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "format_version": FORMAT_VERSION,
        "dry_run_id": fingerprint(conditions),
        "checked_at": checked_at,
        "conditions": conditions,
        "outcome": _outcome(checks),
        "checks": checks,
        "observations": observations,
        "limitations": [
            "sample外の行品質と全件数量は検査していない。",
            "ドライランは原本取込、台帳登録、正規化job、業務承認を実行しない。",
            "READY_FOR_NORMALIZATIONは実データ受入や予測精度を保証しない。",
        ],
    }


def run_dry_run(
    input_root: Path,
    relative_source: str,
    mapping_file: Path,
    output_root: Path,
    limits: DryRunLimits = DEFAULT_LIMITS,
) -> dict:
    payload = collect_dry_run(input_root, relative_source, mapping_file, limits)
    report_uri, report_sha256 = publish_report(payload, output_root)
    return {
        "dry_run_id": payload["dry_run_id"],
        "outcome": payload["outcome"],
        "report_uri": report_uri,
        "report_sha256": report_sha256,
    }
