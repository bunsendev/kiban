"""複数Worker向けPostgreSQL JAN名寄せ台帳。"""

from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import HandlingPeriod, JanMapping, MatchingJob
from .store import SqliteMasterStore


class PostgresMasterStore(SqliteMasterStore):
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

    def _initialize(self):
        with self._raw_connect() as db:
            sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            for statement in sql.split(";"):
                if statement.strip():
                    db.execute(statement)

    def claim(self) -> MatchingJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT matching_job_id FROM matching_jobs WHERE status='QUEUED' "
                "ORDER BY created_at,matching_job_id FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            matching_job_id = row[0]
            db.execute(
                "UPDATE matching_jobs SET status='RUNNING' "
                "WHERE matching_job_id=? AND status='QUEUED'",
                (matching_job_id,),
            )
        return self.get_job(matching_job_id)

    def put_jan_mapping(self, value: JanMapping):
        with self._connect() as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtext(?))",
                (f"jan:{value.jan}:{value.mapping_version}",),
            )
            self._put_jan_mapping(db, value)

    def put_handling_period(self, value: HandlingPeriod):
        with self._connect() as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtext(?))",
                (
                    "handling:"
                    f"{value.canonical_product_id}:{value.center_id}:{value.period_version}",
                ),
            )
            self._put_handling_period(db, value)
