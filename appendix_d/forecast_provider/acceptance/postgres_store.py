"""複数Worker向けPostgreSQL受入台帳。"""

from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import AcceptanceCase
from .store import SqliteAcceptanceStore


class PostgresAcceptanceStore(SqliteAcceptanceStore):
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

    def _connect(self):
        return _Connection(self._raw_connect())

    def _initialize(self) -> None:
        with self._raw_connect() as db:
            for statement in Path(__file__).with_name("schema.sql").read_text(
                encoding="utf-8"
            ).split(";"):
                if statement.strip():
                    db.execute(statement)

    def claim(self) -> AcceptanceCase | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT case_id FROM acceptance_cases WHERE status='QUEUED' "
                "ORDER BY created_at,case_id FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            case_id = row[0]
            db.execute(
                "UPDATE acceptance_cases SET status='RUNNING' "
                "WHERE case_id=? AND status='QUEUED'",
                (case_id,),
            )
        return self.get_case(case_id)
