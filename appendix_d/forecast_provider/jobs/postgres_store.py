"""psycopgによるPostgreSQL RunStore。依存は利用時だけ読み込む。"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .contracts import OriginDefinition, OriginLease
from .sqlite_store import SqliteRunStore


class _HybridRow(dict):
    """PostgreSQLの型をSQLiteストアと同じ値表現で公開する。"""

    def __init__(self, row) -> None:
        super().__init__((key, self._normalize(value)) for key, value in row.items())

    @staticmethod
    def _normalize(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class _Cursor:
    def __init__(self, cursor) -> None:
        self.cursor = cursor

    @property
    def rowcount(self) -> int:
        return self.cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return None if row is None else _HybridRow(row)

    def __iter__(koh):
        return (_HybridRow(row) for row in koh.cursor)


class _Connection:
    def __init__(self, connection) -> None:
        self.connection = connection

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("?", "%s").replace("BEGIN IMMEDIATE", "BEGIN")

    @staticmethod
    def _params(sql: str, params):
        values = list(params)
        if "INSERT INTO forecast_values" in sql and len(values) == 10 and values[6] == "":
            values[6] = None
        return tuple(values)

    def execute(self, sql: str, params=()) -> _Cursor:
        cursor = self.connection.execute(self._sql(sql), self._params(sql, params))
        return _Cursor(cursor)

    def executemany(self, sql: str, params) -> None:
        with self.connection.cursor() as cursor:
            cursor.executemany(self._sql(sql), [self._params(sql, item) for item in params])

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)


class PostgresRunStore(SqliteRunStore):
    """PostgreSQL実装。claimはSKIP LOCKEDで複数Workerを競合させない。"""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.path = Path(".")
        self._initialize()

    def _raw_connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL利用にはpsycopgを追加してください") from exc
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _connect(self) -> _Connection:
        return _Connection(self._raw_connect())

    def _initialize(self) -> None:
        migration = Path(__file__).with_name("migrations") / "001_run_ledger.sql"
        with self._raw_connect() as db:
            for statement in migration.read_text(encoding="utf-8").split(";"):
                if statement.strip():
                    db.execute(statement)

    def claim_next_origin(
        self, run_id: str, worker_id: str, lease_seconds: int
    ) -> OriginLease | None:
        if not worker_id or lease_seconds <= 0:
            raise ValueError("worker_idと正のlease_secondsが必要です")
        with self._raw_connect() as db:
            row = db.execute(
                "SELECT * FROM forecast_origins WHERE run_id=%s AND status='QUEUED' "
                "ORDER BY origin_date LIMIT 1 FOR UPDATE SKIP LOCKED",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            attempt = row["attempt"] + 1
            token = str(uuid.uuid4())
            leased_until = datetime.now(UTC) + timedelta(seconds=lease_seconds)
            db.execute(
                "UPDATE forecast_origins SET status='RUNNING',attempt=%s,error=NULL,"
                "worker_id=%s,lease_token=%s,leased_until=%s "
                "WHERE run_id=%s AND origin_date=%s",
                (attempt, worker_id, token, leased_until, run_id, row["origin_date"]),
            )
            origin_date = row["origin_date"]
            if isinstance(origin_date, str):
                origin_date = date.fromisoformat(origin_date)
            return OriginLease(
                run_id,
                OriginDefinition(origin_date, row["cutoff_at"]),
                attempt,
                worker_id,
                token,
                leased_until,
            )
