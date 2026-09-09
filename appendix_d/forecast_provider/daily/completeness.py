"""予定された論理ファイルの完全性を日別に判定する。"""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .contracts import FileCompleteness, FileSchedule


def evaluate_completeness(
    build_id: str,
    schedule: FileSchedule,
    sources: list[dict],
    start: date,
    end: date,
    as_of: datetime,
    availability_mode: str,
) -> list[FileCompleteness]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_ofはtimezone付き日時です")
    as_of = as_of.astimezone(UTC)
    source_by_path = {item["logical_path"]: item for item in sources}
    expected = defaultdict(list)
    for planned in schedule.definition["files"]:
        file_start = max(date.fromisoformat(planned["target_start"]), start)
        file_end = min(date.fromisoformat(planned["target_end"]), end)
        if file_start > file_end:
            continue
        source = source_by_path.get(planned["logical_path"])
        available_at = _available_at(planned, source, availability_mode)
        problem = (
            "MISSING" if available_at is None or available_at > as_of else _problem(planned, source)
        )
        for target in _dates(file_start, file_end):
            expected[(planned["center_id"], target)].append((planned, problem, available_at))

    centers = sorted({item["center_id"] for item in schedule.definition["files"]})
    results = []
    for center_id in centers:
        for target in _dates(start, end):
            items = expected.get((center_id, target), [])
            missing = sorted(
                item["logical_path"] for item, problem, _ in items if problem == "MISSING"
            )
            invalid = sorted(
                item["logical_path"] for item, problem, _ in items if problem == "INVALID"
            )
            valid = [
                (item, available_at) for item, problem, available_at in items if problem is None
            ]
            if not items or (missing and not valid and not invalid):
                status = "MISSING"
            elif missing or invalid:
                status = "PARTIAL_OR_INVALID"
            else:
                status = "COMPLETE"
            results.append(
                FileCompleteness(
                    build_id,
                    center_id,
                    target.isoformat(),
                    status,
                    len(items),
                    len(valid),
                    status == "COMPLETE"
                    and bool(items)
                    and all(item["absence_means_zero"] for item, _ in valid),
                    (
                        max(available_at for _, available_at in valid).astimezone(UTC).isoformat()
                        if status == "COMPLETE"
                        else as_of.isoformat()
                    ),
                    tuple(missing),
                    tuple(invalid),
                )
            )
    return results


def _problem(planned: dict, source: dict | None) -> str | None:
    if source is None:
        return "MISSING"
    rows = source["rows"]
    if source["status"] != "SUCCEEDED" or any(row["status"] != "ACCEPTED" for row in rows):
        return "INVALID"
    start = date.fromisoformat(planned["target_start"])
    end = date.fromisoformat(planned["target_end"])
    for row in rows:
        try:
            shipment_date = date.fromisoformat(row["shipment_date"])
        except (TypeError, ValueError):
            return "INVALID"
        if row["center_id"] != planned["center_id"] or not start <= shipment_date <= end:
            return "INVALID"
    return None


def _available_at(planned: dict, source: dict | None, mode: str) -> datetime | None:
    if source is None:
        return None
    if mode == "ASSUMED":
        target_end = date.fromisoformat(planned["target_end"])
        return datetime.combine(
            target_end + timedelta(days=1), time.min, tzinfo=ZoneInfo("Asia/Tokyo")
        )
    if mode != "OBSERVED":
        raise ValueError("availability_modeが不正です")
    row_times = [_parse_time(row["available_at"]) for row in source["rows"]]
    if row_times and all(value is not None for value in row_times):
        return max(row_times)
    return _parse_time(source.get("source_created_at"), assume_utc=True)


def _parse_time(value: str | None, *, assume_utc: bool = False) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if not assume_utc:
            return None
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
