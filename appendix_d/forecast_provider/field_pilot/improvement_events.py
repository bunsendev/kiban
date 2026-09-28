"""監査ログとは独立した、機微データを持たない改善用イベント台帳。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

EVENT_TYPES = frozenset({
    "INBOX_CLASSIFIED", "INBOX_VALIDATED", "INBOX_REVIEW", "INBOX_DUPLICATE",
    "VIEW_READY", "VIEW_BLOCKED", "DETAIL_OPENED", "VIEW_COMPLETED",
    "FORECAST_READY", "PROJECTION_READY", "FEFO_READY", "RETRY",
    "OPERATOR_FEEDBACK", "OPERATOR_ACTION",
})
METRIC_KEYS = frozenset({
    "size_bytes", "duration_ms", "row_count", "item_count", "shortage_count",
    "expiry_attention_count", "age_minutes", "retry_count",
})
OUTCOMES = frozenset({"OK", "BLOCKED", "REVIEW", "FAILED"})
ERROR_CODES = frozenset({
    "PDF_HUMAN_REVIEW_REQUIRED", "EXTENSION_MISMATCH", "FORMAT_UNSUPPORTED",
    "ENCODING_UNKNOWN", "HEADER_INVALID", "HEADER_CHANGED", "SCHEMA_UNKNOWN",
    "ROW_SHAPE_INVALID", "CSV_INVALID", "SCHEMA_AMBIGUOUS", "VALUE_INVALID",
    "KNOWN_SCHEMA", "SAME_SHA256", "SAME_TARGET_DIFFERENT_SHA256",
    "VALIDATED_IMPORT_NOT_CONFIGURED", "INVENTORY_JOB_QUEUED",
    "STRICT_VALIDATION_SUCCEEDED",
    "STRICT_VALIDATION_NOT_READY", "STRICT_VALIDATION_FAILED",
    "LEARNING_CANDIDATE_UNAVAILABLE", "INBOX_NOT_READY", "SETUP_REQUIRED",
    "FRESHNESS_POLICY_MISSING", "DATA_NOT_READY", "SNAPSHOT_TIME_INVALID",
    "SNAPSHOT_IN_FUTURE", "SNAPSHOT_BUSINESS_DATE_MISMATCH", "SNAPSHOT_TOO_OLD",
}) | frozenset(
    f"OPERATOR_{step}_{issue}"
    for step in ("UPLOAD", "CHECK", "RESULT", "FINISH")
    for issue in ("UNCLEAR", "BLOCKED", "NOT_UPDATED", "WRONG_RESULT", "OTHER")
) | frozenset(
    f"ACTION_{action}"
    for action in ("REFRESH", "SCAN_REQUESTED", "DETAIL_OPENED", "FINISH_REQUESTED")
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS improvement_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    known_at TEXT NOT NULL,
    business_date TEXT,
    jan TEXT,
    canonical_product_id TEXT,
    location_id TEXT,
    forecast_run_id TEXT,
    inventory_snapshot_id TEXT,
    policy_version TEXT,
    schema_version TEXT,
    application_version TEXT,
    mode TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    outcome TEXT NOT NULL,
    error_code TEXT
);
CREATE INDEX IF NOT EXISTS ix_improvement_date ON improvement_events(business_date,event_type);
"""


def _identifier(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 120 or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
        for char in value
    ):
        raise ValueError(f"{label} must be a safe identifier")
    return value


class ImprovementEventLedger:
    def __init__(self, path: Path):
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("IMPROVEMENT_LEDGER_PATH_INVALID")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(
        self, event_type: str, *, outcome: str, business_date: date | None = None,
        occurred_at: datetime | None = None, known_at: datetime | None = None,
        jan: str | None = None, canonical_product_id: str | None = None,
        location_id: str | None = None,
        forecast_run_id: str | None = None, inventory_snapshot_id: str | None = None,
        policy_version: str | None = None, schema_version: str | None = None,
        application_version: str | None = None, mode: str = "SHADOW",
        metrics: dict | None = None, error_code: str | None = None,
    ) -> str:
        if event_type not in EVENT_TYPES or outcome not in OUTCOMES or mode != "SHADOW":
            raise ValueError("IMPROVEMENT_EVENT_INVALID")
        if error_code is not None and error_code not in ERROR_CODES:
            raise ValueError("IMPROVEMENT_ERROR_CODE_INVALID")
        metrics = metrics or {}
        if not isinstance(metrics, dict) or metrics.keys() - METRIC_KEYS or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or value < 0 or value != value or value == float("inf")
            for value in metrics.values()
        ):
            raise ValueError("IMPROVEMENT_METRICS_INVALID")
        occurred = occurred_at or datetime.now(UTC)
        known = known_at or occurred
        if any(item.tzinfo is None or item.utcoffset() is None for item in (occurred, known)):
            raise ValueError("IMPROVEMENT_TIME_INVALID")
        if known < occurred:
            raise ValueError("IMPROVEMENT_TIME_INVALID")
        if business_date is not None and (
            isinstance(business_date, datetime) or not isinstance(business_date, date)
        ):
            raise ValueError("IMPROVEMENT_DATE_INVALID")
        identifiers = tuple(_identifier(value, label) for label, value in (
            ("jan", jan), ("canonical_product_id", canonical_product_id),
            ("location_id", location_id), ("forecast_run_id", forecast_run_id),
            ("inventory_snapshot_id", inventory_snapshot_id),
            ("policy_version", policy_version), ("schema_version", schema_version),
            ("application_version", application_version),
            ("error_code", error_code),
        ))
        event_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                "INSERT INTO improvement_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id, event_type, occurred.astimezone(UTC).isoformat(),
                    known.astimezone(UTC).isoformat(),
                    business_date.isoformat() if business_date else None,
                    *identifiers[:8], mode,
                    json.dumps(metrics, sort_keys=True, separators=(",", ":")),
                    outcome, identifiers[8],
                ),
            )
        return event_id

    def weekly_summary(self, end_date: date) -> dict:
        start_date = end_date - timedelta(days=6)
        with self._connect() as db:
            rows = db.execute(
                "SELECT event_type,outcome,error_code,count(*) AS n FROM improvement_events "
                "WHERE business_date>=? AND business_date<=? "
                "GROUP BY event_type,outcome,error_code ORDER BY event_type,outcome,error_code",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return {
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
            "event_counts": [dict(row) for row in rows],
            "business_kpis": {
                "stockout_cases": None, "expired_cases": None,
                "interwarehouse_transfer_cases": None,
            },
            "note": "業務KPIは後日実績との結合が未設定のため未計測です。0とは扱いません。",
        }

    def delete_before(self, cutoff: datetime) -> int:
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("RETENTION_CUTOFF_INVALID")
        with self._connect() as db:
            result = db.execute(
                "DELETE FROM improvement_events WHERE occurred_at<?",
                (cutoff.astimezone(UTC).isoformat(),),
            )
            return result.rowcount
