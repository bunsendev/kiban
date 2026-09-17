"""Provider適合試験jobのSQLite/PostgreSQL台帳。"""

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import ConformanceJob


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteConformanceJobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    @staticmethod
    def _job(row) -> ConformanceJob:
        values = dict(row)
        for name in ("requested_at", "started_at", "finished_at"):
            value = values.get(name)
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                values[name] = value.astimezone(UTC).isoformat()
        return ConformanceJob(**values)

    def enqueue(
        self, experiment_id: str, provider_id: str, model_id: str, requested_by: str
    ) -> ConformanceJob:
        active = self._active(experiment_id)
        if active is not None:
            return active
        value = ConformanceJob(
            str(uuid.uuid4()), experiment_id, provider_id, model_id,
            requested_by, "QUEUED", _now(),
        )
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO provider_conformance_jobs("
                    "job_id,experiment_id,provider_id,model_id,requested_by,status,requested_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        value.job_id, value.experiment_id, value.provider_id, value.model_id,
                        value.requested_by, value.status, value.requested_at,
                    ),
                )
        except Exception:
            # 同時要求は部分UNIQUE indexで一件に収束させる。
            active = self._active(experiment_id)
            if active is not None:
                return active
            raise
        return value

    def _active(self, experiment_id: str) -> ConformanceJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM provider_conformance_jobs WHERE experiment_id=? "
                "AND status IN ('QUEUED','RUNNING') ORDER BY requested_at DESC LIMIT 1",
                (experiment_id,),
            ).fetchone()
        return None if row is None else self._job(row)

    def get_job(self, job_id: str) -> ConformanceJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM provider_conformance_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return None if row is None else self._job(row)

    def list_jobs(self, experiment_id: str | None = None) -> list[ConformanceJob]:
        sql = "SELECT * FROM provider_conformance_jobs"
        params = ()
        if experiment_id is not None:
            sql += " WHERE experiment_id=?"
            params = (experiment_id,)
        sql += " ORDER BY requested_at DESC,job_id DESC"
        with self._connect() as db:
            return [self._job(row) for row in db.execute(sql, params)]

    def claim(self, provider_id: str) -> ConformanceJob | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT job_id FROM provider_conformance_jobs "
                "WHERE provider_id=? AND status='QUEUED' ORDER BY requested_at,job_id LIMIT 1",
                (provider_id,),
            ).fetchone()
            if row is None:
                return None
            job_id = row[0]
            changed = db.execute(
                "UPDATE provider_conformance_jobs SET status='RUNNING',started_at=?,"
                "error_code=NULL,error_message=NULL WHERE job_id=? AND status='QUEUED'",
                (_now(), job_id),
            ).rowcount
            if changed != 1:
                return None
        return self.get_job(job_id)

    def complete(self, job_id: str, conformance_id: str) -> None:
        with self._connect() as db:
            changed = db.execute(
                "UPDATE provider_conformance_jobs SET status='SUCCEEDED',finished_at=?,"
                "conformance_id=?,error_code=NULL,error_message=NULL "
                "WHERE job_id=? AND status='RUNNING'",
                (_now(), conformance_id, job_id),
            ).rowcount
        if changed != 1:
            raise ValueError("RUNNINGの適合試験jobだけを完了できます")

    def fail(self, job_id: str, error_code: str, error_message: str) -> None:
        with self._connect() as db:
            changed = db.execute(
                "UPDATE provider_conformance_jobs SET status='FAILED',finished_at=?,"
                "error_code=?,error_message=? WHERE job_id=? AND status='RUNNING'",
                (_now(), error_code[:80], error_message[:500], job_id),
            ).rowcount
        if changed != 1:
            raise ValueError("RUNNINGの適合試験jobだけを失敗にできます")


class PostgresConformanceJobStore(SqliteConformanceJobStore):
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.path = Path(".")
        self._initialize()

    def _raw_connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _connect(self):
        return _Connection(self._raw_connect())

    def _initialize(self) -> None:
        with self._raw_connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(26091701)")
            sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            for statement in sql.split(";"):
                if statement.strip():
                    db.execute(statement)

    def claim(self, provider_id: str) -> ConformanceJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT job_id FROM provider_conformance_jobs "
                "WHERE provider_id=? AND status='QUEUED' "
                "ORDER BY requested_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1",
                (provider_id,),
            ).fetchone()
            if row is None:
                return None
            job_id = row[0]
            db.execute(
                "UPDATE provider_conformance_jobs SET status='RUNNING',started_at=?,"
                "error_code=NULL,error_message=NULL WHERE job_id=? AND status='QUEUED'",
                (_now(), job_id),
            )
        return self.get_job(job_id)
