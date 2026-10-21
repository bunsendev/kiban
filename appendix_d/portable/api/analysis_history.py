"""Portable history identity independent of filesystem copy/extraction times."""

from datetime import datetime


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def history_record(report, recorded_at=None):
    created = report.get("created_at")
    source = "analysis"
    if timestamp(created) is None:
        created, source = recorded_at, "daily_run"
    if timestamp(created) is None:
        created, source = None, "unknown"
    warehouses = sorted({
        str(item["center"]) for item in report.get("source_files", [])
        if item.get("center")
    } | {
        str(item["center"]) for item in report.get("center_windows", [])
        if item.get("center")
    })
    return {"created_at": created, "created_at_source": source, "warehouses": warehouses}


def history_sort_key(item):
    value = timestamp(item.get("created_at"))
    return (value is not None, value or 0, str(item.get("analysis_id", "")))
