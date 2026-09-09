"""日次台帳のDB行と永続型の相互変換。"""

import json
from decimal import Decimal

from .contracts import DailyBuildJob, DailyValue, FileCompleteness, FileSchedule


def schedule_from_row(row) -> FileSchedule:
    return FileSchedule(
        row["schedule_id"],
        row["format_version"],
        row["content_hash"],
        json.loads(row["definition_json"]),
    )


def job_from_row(row) -> DailyBuildJob:
    return DailyBuildJob(
        row["build_id"],
        row["format_version"],
        row["condition_fingerprint"],
        json.loads(row["definition_json"]),
        row["status"],
        row["snapshot_id"],
        row["data_uri"],
        row["data_sha256"],
        row["error"],
    )


def completeness_from_row(row) -> FileCompleteness:
    return FileCompleteness(
        row["build_id"],
        row["center_id"],
        row["target_date"],
        row["status"],
        row["expected_count"],
        row["valid_count"],
        bool(row["zero_confirmable"]),
        row["available_at"],
        tuple(json.loads(row["missing_paths_json"])),
        tuple(json.loads(row["invalid_paths_json"])),
    )


def daily_value_from_row(row) -> DailyValue:
    return DailyValue(
        row["build_id"],
        row["canonical_product_id"],
        row["center_id"],
        row["ds"],
        row["unique_id"],
        to_decimal(row["raw_quantity"]),
        to_decimal(row["y"]),
        row["state"],
        row["available_at"],
        row["issue"],
    )


def encode_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def to_decimal(value) -> Decimal | None:
    return None if value is None else Decimal(value)
