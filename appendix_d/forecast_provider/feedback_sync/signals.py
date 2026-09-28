"""原本・担当者・対象IDを読まず、学習と設定変更の件数だけ収集する。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

LEARNING_ACTIONS = frozenset({
    "OPERATOR_CONFIRM", "DISAGREE", "ADMIN_APPROVE", "ADMIN_REJECT",
    "VALIDATION_FAILED", "ADMIN_DEACTIVATE",
})
CHANGE_TYPES = frozenset({"JAN_MAPPING", "INVENTORY_TIME_POLICY"})


def _counts(path: Path, query: str, start: str, end: str, allowed: frozenset[str]) -> list[dict]:
    if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
        return []
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            rows = db.execute(query, (start, end)).fetchall()
    except sqlite3.DatabaseError:
        return []
    return [{"kind": kind, "count": min(count, 10000)}
            for kind, count in rows if kind in allowed and type(count) is int and count > 0]


def collect_context(inbox_root: Path, settings_root: Path, day: date) -> dict:
    start = datetime.combine(day, time.min, tzinfo=UTC) - timedelta(hours=9)
    end = start + timedelta(days=1)
    window = start.isoformat(), end.isoformat()
    return {
        "learning_summary": _counts(
            inbox_root / "inbox.sqlite3",
            "SELECT action,COUNT(*) FROM learning_events WHERE recorded_at>=? "
            "AND recorded_at<? GROUP BY action ORDER BY action",
            *window, LEARNING_ACTIONS,
        ),
        "change_summary": _counts(
            settings_root / "field-settings.sqlite3",
            "SELECT change_type,COUNT(*) FROM setting_changes WHERE changed_at>=? "
            "AND changed_at<? GROUP BY change_type ORDER BY change_type",
            *window, CHANGE_TYPES,
        ),
    }
