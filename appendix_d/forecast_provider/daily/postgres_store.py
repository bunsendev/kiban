"""複数Worker向けPostgreSQL日次build台帳。"""

from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import DailyBuildJob
from .store import SqliteDailyStore


class PostgresDailyStore(SqliteDailyStore):
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
            root = Path(__file__).parent
            for name in ("schema.sql", "postgres_upgrade.sql"):
                for statement in (root / name).read_text(encoding="utf-8").split(";"):
                    if statement.strip():
                        db.execute(statement)

    def claim(self) -> DailyBuildJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT build_id FROM daily_build_jobs WHERE status='QUEUED' "
                "ORDER BY created_at,build_id FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            build_id = row[0]
            db.execute(
                "UPDATE daily_build_jobs SET status='RUNNING' WHERE build_id=? AND status='QUEUED'",
                (build_id,),
            )
        return self.get_job(build_id)
