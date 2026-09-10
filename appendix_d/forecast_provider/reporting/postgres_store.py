"""比較CSVと採用判断のPostgreSQL台帳。"""

from pathlib import Path

from ..jobs.postgres_store import _Connection
from .store import SqliteReportingStore


class PostgresReportingStore(SqliteReportingStore):
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
            for statement in Path(__file__).with_name("schema.sql").read_text(
                encoding="utf-8"
            ).split(";"):
                if statement.strip():
                    db.execute(statement)
