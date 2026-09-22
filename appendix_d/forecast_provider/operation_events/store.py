from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from statistics import median

from .contracts import OperationEvent


class SqliteOperationEventStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    def append(self, value: OperationEvent) -> OperationEvent:
        row_values = _values(value)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO operation_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                row_values,
            )
            row = db.execute(
                "SELECT * FROM operation_events WHERE event_id=?", (value.event_id,)
            ).fetchone()
        current = _event(row)
        if replace(current, received_at=value.received_at) != value:
            raise ValueError("同じ操作イベントIDの内容は変更できません")
        return current

    def list_events(
        self,
        *,
        since: datetime | None = None,
        screen: str | None = None,
        event_name: str | None = None,
        limit: int = 200,
    ) -> list[OperationEvent]:
        clauses, params = [], []
        if since is not None:
            clauses.append("received_at>=?")
            params.append(since.isoformat())
        if screen is not None:
            clauses.append("screen=?")
            params.append(screen)
        if event_name is not None:
            clauses.append("event_name=?")
            params.append(event_name)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM operation_events{where} "
                "ORDER BY received_at DESC,event_id LIMIT ?",
                params,
            )
            return [_event(row) for row in rows]

    def summarize(self, since: datetime) -> dict:
        values = self.list_events(since=since, limit=100_000)
        sessions: dict[str, set[str]] = {}
        for value in values:
            sessions.setdefault(value.flow_session_id, set()).add(value.event_name)
        event_counts = Counter(value.event_name for value in values)
        source_modes = Counter(
            str(value.metadata["source_mode"])
            for value in values
            if value.metadata.get("source_mode")
        )
        error_kinds = Counter(
            str(value.metadata["error_kind"])
            for value in values
            if value.outcome == "FAILURE" and value.metadata.get("error_kind")
        )
        durations = {}
        for name in ("ANALYSIS_REQUESTED", "ANALYSIS_ACCEPTED"):
            elapsed = sorted(
                value.elapsed_ms
                for value in values
                if value.event_name == name and value.elapsed_ms is not None
            )
            durations[name] = {
                "count": len(elapsed),
                "median_ms": int(median(elapsed)) if elapsed else None,
                "p90_ms": _percentile(elapsed, 0.9),
            }
        funnel_names = ("CONNECTED", "SOURCE_SELECTED", "ANALYSIS_REQUESTED", "ANALYSIS_ACCEPTED")
        return {
            "since": since.isoformat(),
            "total_events": len(values),
            "session_count": len(sessions),
            "operator_count": len({value.subject for value in values}),
            "event_counts": dict(event_counts),
            "funnel": {
                name: sum(name in names for names in sessions.values()) for name in funnel_names
            },
            "source_modes": dict(source_modes),
            "error_kinds": dict(error_kinds),
            "durations": durations,
        }

    def purge_before(self, before: datetime) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "DELETE FROM operation_events WHERE received_at<?", (before.isoformat(),)
            )
            return cursor.rowcount


def _values(value: OperationEvent) -> tuple:
    return (
        value.event_id,
        value.flow_session_id,
        value.subject,
        value.screen,
        value.event_name,
        value.step,
        value.sequence,
        value.outcome,
        value.elapsed_ms,
        json.dumps(value.metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        value.occurred_at.isoformat(),
        value.received_at.isoformat(),
    )


def _event(row) -> OperationEvent:
    return OperationEvent(
        row["event_id"],
        row["flow_session_id"],
        row["subject"],
        row["screen"],
        row["event_name"],
        int(row["step"]),
        int(row["sequence"]),
        row["outcome"],
        None if row["elapsed_ms"] is None else int(row["elapsed_ms"]),
        json.loads(row["metadata_json"]),
        datetime.fromisoformat(str(row["occurred_at"])),
        datetime.fromisoformat(str(row["received_at"])),
    )


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    return int(values[min(len(values) - 1, round((len(values) - 1) * fraction))])
