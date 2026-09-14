"""mappingドライランjob台帳のSQLite/PostgreSQL実装。"""

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .jobs import MappingDryRunJob


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteMappingDryRunJobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    @staticmethod
    def _job(row) -> MappingDryRunJob:
        return MappingDryRunJob(**dict(row))

    def enqueue(
        self, source_path: str, mapping_id: str, requested_by: str, sample_rows: int
    ) -> MappingDryRunJob:
        if not 1 <= sample_rows <= 10_000:
            raise ValueError("sample rowsは1以上10000以下です")
        value = MappingDryRunJob(
            str(uuid.uuid4()),
            source_path,
            mapping_id,
            requested_by,
            "QUEUED",
            sample_rows,
            _now(),
        )
        with self._connect() as db:
            db.execute(
                "INSERT INTO mapping_dry_run_jobs("
                "job_id,source_path,mapping_id,requested_by,status,sample_rows,requested_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    value.job_id,
                    value.source_path,
                    value.mapping_id,
                    value.requested_by,
                    value.status,
                    value.sample_rows,
                    value.requested_at,
                ),
            )
        return value

    def get_job(self, job_id: str) -> MappingDryRunJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT job_id,source_path,mapping_id,requested_by,status,sample_rows,"
                "requested_at,started_at,finished_at,dry_run_id,outcome,report_sha256,error_code "
                "FROM mapping_dry_run_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        return None if row is None else self._job(row)

    def list_jobs(self) -> list[MappingDryRunJob]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT job_id,source_path,mapping_id,requested_by,status,sample_rows,"
                "requested_at,started_at,finished_at,dry_run_id,outcome,report_sha256,error_code "
                "FROM mapping_dry_run_jobs ORDER BY requested_at DESC,job_id DESC"
            )
            return [self._job(row) for row in rows]

    def claim(self) -> MappingDryRunJob | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT job_id FROM mapping_dry_run_jobs WHERE status='QUEUED' "
                "ORDER BY requested_at,job_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            job_id = row[0]
            db.execute(
                "UPDATE mapping_dry_run_jobs SET status='RUNNING',started_at=? "
                "WHERE job_id=? AND status='QUEUED'",
                (_now(), job_id),
            )
        return self.get_job(job_id)

    def complete(
        self, job_id: str, dry_run_id: str, outcome: str, report_sha256: str
    ) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE mapping_dry_run_jobs SET status='SUCCEEDED',finished_at=?,dry_run_id=?,"
                "outcome=?,report_sha256=?,error_code=NULL WHERE job_id=?",
                (_now(), dry_run_id, outcome, report_sha256, job_id),
            )

    def fail(self, job_id: str, error_code: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE mapping_dry_run_jobs SET status='FAILED',finished_at=?,error_code=? "
                "WHERE job_id=?",
                (_now(), error_code, job_id),
            )


class PostgresMappingDryRunJobStore(SqliteMappingDryRunJobStore):
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
            # APIとWorkerの同時初回起動でもPostgreSQL catalog DDLを競合させない。
            db.execute("SELECT pg_advisory_xact_lock(26091401)")
            sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            for statement in sql.split(";"):
                if statement.strip():
                    db.execute(statement)

    def claim(self) -> MappingDryRunJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT job_id FROM mapping_dry_run_jobs WHERE status='QUEUED' "
                "ORDER BY requested_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            job_id = row[0]
            db.execute(
                "UPDATE mapping_dry_run_jobs SET status='RUNNING',started_at=? "
                "WHERE job_id=? AND status='QUEUED'",
                (_now(), job_id),
            )
        return self.get_job(job_id)
