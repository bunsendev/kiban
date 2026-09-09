"""予定定義・休業日・日次buildの検証と内容アドレス化。"""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta

from .contracts import ClosedDay, DailyBuildJob, FileSchedule

FORMAT_VERSION = 1


def make_file_schedule(definition: dict) -> FileSchedule:
    required = {"schedule_version", "valid_from", "valid_to", "files"}
    if set(definition) != required:
        raise ValueError("予定ファイル定義の項目が契約と一致しません")
    _required(schedule_version=definition["schedule_version"])
    start, end = _date_range(definition["valid_from"], definition["valid_to"])
    files = definition["files"]
    if not isinstance(files, list) or not files:
        raise ValueError("予定ファイルは1件以上必要です")
    normalized_files = []
    paths = set()
    file_fields = {
        "logical_path",
        "center_id",
        "file_type",
        "target_start",
        "target_end",
        "absence_means_zero",
    }
    for item in files:
        if not isinstance(item, dict) or set(item) != file_fields:
            raise ValueError("予定ファイル項目が契約と一致しません")
        _required(
            logical_path=item["logical_path"],
            center_id=item["center_id"],
            file_type=item["file_type"],
        )
        if item["logical_path"] in paths:
            raise ValueError("logical_pathは予定内で重複できません")
        paths.add(item["logical_path"])
        target_start, target_end = _date_range(item["target_start"], item["target_end"])
        if target_start < start or target_end > end:
            raise ValueError("予定ファイルの対象日は定義の有効期間内です")
        if not isinstance(item["absence_means_zero"], bool):
            raise ValueError("absence_means_zeroはboolです")
        normalized_files.append(dict(item))
    normalized = {
        **definition,
        "files": sorted(normalized_files, key=lambda item: item["logical_path"]),
    }
    fingerprint = _digest(normalized)
    return FileSchedule(f"schedule-{fingerprint}", FORMAT_VERSION, fingerprint, normalized)


def make_closed_day(
    center_id: str,
    closed_date: str,
    closure_version: str,
    available_at: str,
    approved_by: str,
    reason: str,
) -> ClosedDay:
    _required(
        center_id=center_id,
        closed_date=closed_date,
        closure_version=closure_version,
        available_at=available_at,
        approved_by=approved_by,
        reason=reason,
    )
    date.fromisoformat(closed_date)
    known_at = datetime.fromisoformat(available_at)
    if known_at.tzinfo is None or known_at.utcoffset() is None:
        raise ValueError("available_atはtimezone付き日時です")
    return ClosedDay(
        str(uuid.uuid4()),
        center_id,
        closed_date,
        closure_version,
        known_at.astimezone(UTC).isoformat(),
        approved_by,
        reason,
        datetime.now(UTC).isoformat(),
    )


def make_daily_build(definition: dict) -> DailyBuildJob:
    required = {
        "schedule_id",
        "normalization_ids",
        "mapping_version",
        "period_version",
        "closure_version",
        "as_of",
        "selection_version",
        "selected_series",
        "train_start",
        "train_end",
        "test_start",
        "test_end",
        "origin_interval_days",
        "max_horizon",
        "primary_horizon_max",
        "report_horizons",
        "availability_mode",
    }
    if set(definition) != required:
        raise ValueError("日次build定義の項目が契約と一致しません")
    _required(
        schedule_id=definition["schedule_id"],
        mapping_version=definition["mapping_version"],
        period_version=definition["period_version"],
        as_of=definition["as_of"],
        selection_version=definition["selection_version"],
        availability_mode=definition["availability_mode"],
    )
    if definition["closure_version"] is not None:
        _required(closure_version=definition["closure_version"])
    as_of = datetime.fromisoformat(definition["as_of"])
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_ofはtimezone付き日時です")
    normalizations = definition["normalization_ids"]
    if (
        not isinstance(normalizations, list)
        or not normalizations
        or len(normalizations) != len(set(normalizations))
        or not all(isinstance(value, str) and value for value in normalizations)
    ):
        raise ValueError("normalization_idsは重複のない非空listです")
    series = definition["selected_series"]
    series_fields = {"canonical_product_id", "center_id"}
    if not isinstance(series, list) or not series:
        raise ValueError("selected_seriesは1件以上必要です")
    if any(not isinstance(item, dict) or set(item) != series_fields for item in series):
        raise ValueError("selected_seriesの項目が契約と一致しません")
    for item in series:
        _required(**item)
    series_keys = [(item["canonical_product_id"], item["center_id"]) for item in series]
    if len(series_keys) != len(set(series_keys)):
        raise ValueError("selected_seriesは重複できません")
    _, train_end = _date_range(definition["train_start"], definition["train_end"])
    test_start, _ = _date_range(definition["test_start"], definition["test_end"])
    if train_end + timedelta(days=1) != test_start:
        raise ValueError("TRAIN終了日の翌日をTEST開始日にします")
    for name in ("origin_interval_days", "max_horizon", "primary_horizon_max"):
        value = definition[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name}は1以上の整数です")
    if definition["max_horizon"] > 400:
        raise ValueError("max_horizonは400以下です")
    if definition["primary_horizon_max"] > definition["max_horizon"]:
        raise ValueError("primary_horizon_maxはmax_horizon以下です")
    horizons = definition["report_horizons"]
    if (
        not isinstance(horizons, list)
        or not horizons
        or len(horizons) != len(set(horizons))
        or any(isinstance(value, bool) or not isinstance(value, int) for value in horizons)
        or any(value < 1 or value > definition["max_horizon"] for value in horizons)
    ):
        raise ValueError("report_horizonsはmax_horizon内の重複しない整数です")
    if definition["availability_mode"] not in {"ASSUMED", "OBSERVED"}:
        raise ValueError("availability_modeが不正です")
    normalized = {
        **definition,
        "normalization_ids": sorted(normalizations),
        "selected_series": [
            {"canonical_product_id": product_id, "center_id": center_id}
            for product_id, center_id in sorted(series_keys)
        ],
        "report_horizons": sorted(horizons),
        "as_of": as_of.astimezone(UTC).isoformat(),
    }
    fingerprint = _digest(normalized)
    return DailyBuildJob(f"daily-{fingerprint}", FORMAT_VERSION, fingerprint, normalized, "QUEUED")


def series_id(canonical_product_id: str, center_id: str) -> str:
    return f"{canonical_product_id}::{center_id}"


def _date_range(start_value: str, end_value: str) -> tuple[date, date]:
    start = date.fromisoformat(start_value)
    end = date.fromisoformat(end_value)
    if end < start:
        raise ValueError("終了日は開始日以降です")
    return start, end


def _required(**values) -> None:
    empty = [name for name, value in values.items() if not isinstance(value, str) or not value]
    if empty:
        raise ValueError(f"必須項目が空です: {', '.join(empty)}")


def _digest(value: dict) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
