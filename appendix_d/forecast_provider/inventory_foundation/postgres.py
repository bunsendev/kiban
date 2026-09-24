"""Phase 3S-1 inventory foundationのPostgreSQL永続化。"""

from __future__ import annotations

from pathlib import Path

from ..jobs.postgres_store import _Connection
from .store import SqliteInventoryFoundationStore


class PostgresInventoryFoundationStore(SqliteInventoryFoundationStore):
    MIGRATION_LOCK_ID = 26092431

    def __init__(self, dsn: str):
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

    def _connect(self):
        return _Connection(self._raw_connect())

    def _initialize(self) -> None:
        statements = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8").split(";")
        with self._raw_connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (self.MIGRATION_LOCK_ID,))
            for statement in statements:
                if statement.strip():
                    db.execute(statement)

