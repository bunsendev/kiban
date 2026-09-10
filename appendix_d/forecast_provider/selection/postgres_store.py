"""複数Worker向けPostgreSQL重要品目選定台帳。"""

from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import CandidateJob
from .store import SqliteSelectionStore


class PostgresSelectionStore(SqliteSelectionStore):
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

    def claim(self) -> CandidateJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT candidate_job_id FROM selection_candidate_jobs WHERE status='QUEUED' "
                "ORDER BY created_at,candidate_job_id FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            candidate_job_id = row[0]
            db.execute(
                "UPDATE selection_candidate_jobs SET status='RUNNING' "
                "WHERE candidate_job_id=? AND status='QUEUED'",
                (candidate_job_id,),
            )
        return self.get_candidate_job(candidate_job_id)
