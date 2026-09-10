"""reporting台帳のJSON表現とDB行変換。"""

import json

from .contracts import AdoptionRecord, ExportRecord


def encode_json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def export_from_row(row) -> ExportRecord:
    return ExportRecord(
        row["export_id"],
        int(row["format_version"]),
        row["condition_fingerprint"],
        row["comparison_id"],
        row["export_version"],
        row["baseline_run_id"],
        row["requested_by"],
        row["output_uri"],
        row["output_sha256"],
        int(row["row_count"]),
        row["created_at"],
    )


def adoption_from_row(row) -> AdoptionRecord:
    return AdoptionRecord(
        row["adoption_id"],
        int(row["format_version"]),
        row["condition_fingerprint"],
        row["adoption_version"],
        row["comparison_id"],
        row["acceptance_case_id"],
        row["decision"],
        row["selected_run_id"],
        row["fallback_run_id"],
        json.loads(row["target_json"]),
        row["decided_by"],
        row["reason"],
        row["decided_at"],
    )
