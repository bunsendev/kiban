from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from .contracts import OperationEvent

EVENT_NAMES = frozenset(
    {
        "CONNECTED",
        "SOURCE_MODE_CHANGED",
        "SOURCE_SELECTED",
        "SOURCE_CLEARED",
        "ANALYSIS_REQUESTED",
        "ANALYSIS_ACCEPTED",
        "ANALYSIS_FAILED",
        "STEP_VIEWED",
        "STEP_COMPLETED",
    }
)
OUTCOMES = frozenset({"INFO", "SUCCESS", "FAILURE", "CANCELLED"})
ALLOWED_METADATA_KEYS = frozenset(
    {
        "source_mode",
        "file_kind",
        "file_size_bucket",
        "source_count_bucket",
        "mapping_match",
        "error_kind",
        "result_kind",
        "viewport_bucket",
        "retry_count",
        "flow_version",
    }
)


def make_operation_event(payload: dict, subject: str, received_at: datetime | None = None):
    event_id = str(UUID(str(payload["event_id"])))
    flow_session_id = str(UUID(str(payload["flow_session_id"])))
    screen = str(payload["screen"])
    event_name = str(payload["event_name"])
    outcome = str(payload["outcome"])
    step = int(payload["step"])
    sequence = int(payload["sequence"])
    elapsed_ms = payload.get("elapsed_ms")
    metadata = dict(payload.get("metadata") or {})
    occurred_at = payload["occurred_at"]
    if event_name not in EVENT_NAMES:
        raise ValueError("未対応の操作イベントです")
    if outcome not in OUTCOMES:
        raise ValueError("操作結果が不正です")
    if not 1 <= step <= 4 or not 1 <= sequence <= 10_000:
        raise ValueError("操作順序が不正です")
    if elapsed_ms is not None and not 0 <= int(elapsed_ms) <= 86_400_000:
        raise ValueError("操作時間が不正です")
    if set(metadata) - ALLOWED_METADATA_KEYS:
        raise ValueError("記録できない操作情報が含まれています")
    if any(not _safe_metadata_value(value) for value in metadata.values()):
        raise ValueError("操作情報の値が不正です")
    if not 1 <= len(screen) <= 40 or not 1 <= len(subject) <= 255:
        raise ValueError("画面または担当者情報が不正です")
    if occurred_at.tzinfo is None:
        raise ValueError("操作時刻にはtimezoneが必要です")
    return OperationEvent(
        event_id,
        flow_session_id,
        subject,
        screen,
        event_name,
        step,
        sequence,
        outcome,
        None if elapsed_ms is None else int(elapsed_ms),
        metadata,
        occurred_at.astimezone(UTC),
        (received_at or datetime.now(UTC)).astimezone(UTC),
    )


def _safe_metadata_value(value) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return -1_000_000 <= value <= 1_000_000
    return isinstance(value, str) and len(value) <= 80
