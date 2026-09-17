"""Worker heartbeatのSQLite/PostgreSQL共通操作。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import (
    StaleWorkerHeartbeat,
    WorkerHeartbeat,
    WorkerState,
)


class SqliteWorkerStatusStore:
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

    def register(
        self,
        worker_id: str,
        instance_id: str,
        provider_id: str,
        *,
        now: datetime | None = None,
    ) -> WorkerHeartbeat:
        _required(worker_id=worker_id, instance_id=instance_id, provider_id=provider_id)
        timestamp = _utc(now)
        with self._connect() as db:
            db.execute(
                "INSERT INTO worker_heartbeats VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(worker_id) DO UPDATE SET "
                "instance_id=excluded.instance_id,provider_id=excluded.provider_id,"
                "state=excluded.state,current_run_id=excluded.current_run_id,"
                "started_at=excluded.started_at,heartbeat_at=excluded.heartbeat_at",
                (
                    worker_id,
                    instance_id,
                    provider_id,
                    WorkerState.IDLE.value,
                    None,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                ),
            )
            return _worker(
                db.execute(
                    "SELECT * FROM worker_heartbeats WHERE worker_id=?", (worker_id,)
                ).fetchone()
            )

    def heartbeat(
        self,
        worker_id: str,
        instance_id: str,
        state: WorkerState,
        current_run_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> WorkerHeartbeat:
        _required(worker_id=worker_id, instance_id=instance_id)
        state = WorkerState(state)
        if state == WorkerState.IDLE and current_run_id is not None:
            raise ValueError("IDLE Workerへcurrent_run_idは指定できません")
        if state == WorkerState.WORKING:
            _required(current_run_id=current_run_id)
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE worker_heartbeats SET state=?,current_run_id=?,heartbeat_at=? "
                "WHERE worker_id=? AND instance_id=?",
                (state.value, current_run_id, _utc(now).isoformat(), worker_id, instance_id),
            )
            if cursor.rowcount != 1:
                raise StaleWorkerHeartbeat("Worker instanceが置き換えられています")
            return _worker(
                db.execute(
                    "SELECT * FROM worker_heartbeats WHERE worker_id=?", (worker_id,)
                ).fetchone()
            )

    def list_workers(self) -> list[WorkerHeartbeat]:
        with self._connect() as db:
            return [
                _worker(row)
                for row in db.execute(
                    "SELECT * FROM worker_heartbeats ORDER BY provider_id,worker_id"
                )
            ]


class PostgresWorkerStatusStore(SqliteWorkerStatusStore):
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.path = Path(".")
        self._initialize()

    def _raw_connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL利用にはpsycopgが必要です") from exc
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _connect(self):
        return _Connection(self._raw_connect())

    def _initialize(self) -> None:
        with self._raw_connect() as db:
            for statement in Path(__file__).with_name("schema_postgres.sql").read_text(
                encoding="utf-8"
            ).split(";"):
                if statement.strip():
                    db.execute(statement)


def _required(**values: str | None) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise ValueError(f"必須文字列が空です: {sorted(values)}")


def _utc(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Worker heartbeat時刻はtimezone付きです")
    return result.astimezone(UTC)


def _worker(row) -> WorkerHeartbeat:
    return WorkerHeartbeat(
        row["worker_id"],
        row["instance_id"],
        row["provider_id"],
        WorkerState(row["state"]),
        row["current_run_id"],
        datetime.fromisoformat(str(row["started_at"])),
        datetime.fromisoformat(str(row["heartbeat_at"])),
    )
