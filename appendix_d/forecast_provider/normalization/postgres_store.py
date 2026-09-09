"""複数Worker向けPostgreSQL正規化台帳。"""

from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import NormalizationJob
from .store import SqliteNormalizationStore


class PostgresNormalizationStore(SqliteNormalizationStore):
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.path = Path(".")
        self._initialize()

    def _raw_connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _connect(self):
        return _Connection(self._raw_connect())

    def _initialize(self):
        with self._raw_connect() as db:
            sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            for statement in sql.split(";"):
                if statement.strip():
                    db.execute(statement)

    def claim(self) -> NormalizationJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT normalization_id FROM normalization_jobs WHERE status='QUEUED' "
                "ORDER BY created_at,normalization_id FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            normalization_id = row[0]
            db.execute(
                "UPDATE normalization_jobs SET status='RUNNING' "
                "WHERE normalization_id=? AND status='QUEUED'",
                (normalization_id,),
            )
        return self.get_job(normalization_id)
