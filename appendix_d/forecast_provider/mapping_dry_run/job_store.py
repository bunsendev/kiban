"""mappingドライランjob台帳のSQLite/PostgreSQL実装。"""

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .jobs import MappingDryRunBatch, MappingDryRunJob


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
        values = dict(row)
        for name in ("requested_at", "started_at", "finished_at"):
            value = values.get(name)
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                values[name] = value.astimezone(UTC).isoformat()
        return MappingDryRunJob(**values)

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
                "ORDER BY requested_at,rowid LIMIT 1"
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

    def complete(self, job_id: str, dry_run_id: str, outcome: str, report_sha256: str) -> None:
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

    def enqueue_batch(
        self, source_prefix, source_paths, mapping_id, requested_by, sample_rows, excluded_count
    ):
        if not source_paths:
            raise ValueError("一括検証の対象CSVがありません")
        batch = MappingDryRunBatch(
            str(uuid.uuid4()),
            source_prefix,
            mapping_id,
            requested_by,
            sample_rows,
            _now(),
            len(source_paths),
            excluded_count,
        )
        with self._connect() as db:
            db.execute("BEGIN")
            db.execute(
                "INSERT INTO mapping_dry_run_batches("
                "batch_id,source_prefix,mapping_id,requested_by,"
                "sample_rows,requested_at,selected_count,excluded_count) VALUES (?,?,?,?,?,?,?,?)",
                tuple(batch.__dict__.values()),
            )
            for path in source_paths:
                job = MappingDryRunJob(
                    str(uuid.uuid4()),
                    path,
                    mapping_id,
                    requested_by,
                    "QUEUED",
                    sample_rows,
                    batch.requested_at,
                )
                db.execute(
                    "INSERT INTO mapping_dry_run_jobs("
                    "job_id,source_path,mapping_id,requested_by,status,"
                    "sample_rows,requested_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        job.job_id,
                        job.source_path,
                        job.mapping_id,
                        job.requested_by,
                        job.status,
                        job.sample_rows,
                        job.requested_at,
                    ),
                )
                db.execute(
                    "INSERT INTO mapping_dry_run_batch_jobs(batch_id,job_id) VALUES (?,?)",
                    (batch.batch_id, job.job_id),
                )
        return batch

    def get_batch(self, batch_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM mapping_dry_run_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if row is None:
                return None
            jobs = db.execute(
                "SELECT j.* FROM mapping_dry_run_jobs j "
                "JOIN mapping_dry_run_batch_jobs b ON b.job_id=j.job_id "
                "WHERE b.batch_id=? ORDER BY j.source_path",
                (batch_id,),
            ).fetchall()
        return self._batch_summary(
            MappingDryRunBatch(**dict(row)), [self._job(job) for job in jobs]
        )

    @staticmethod
    def _batch_summary(batch, jobs):
        counts = dict.fromkeys(("QUEUED", "RUNNING", "SUCCEEDED", "FAILED"), 0)
        outcomes = dict.fromkeys(("READY_FOR_NORMALIZATION", "REVIEW_REQUIRED", "BLOCKED"), 0)
        for job in jobs:
            counts[job.status] += 1
            if job.outcome:
                outcomes[job.outcome] += 1
        complete = counts["SUCCEEDED"] + counts["FAILED"] == batch.selected_count
        return {
            **batch.__dict__,
            "status": "COMPLETED" if complete else "RUNNING",
            "counts": counts,
            "outcomes": outcomes,
            "jobs": [job.__dict__ for job in jobs],
        }


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
            for column in ("requested_at", "started_at", "finished_at"):
                row = db.execute(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema=current_schema() "
                    "AND table_name='mapping_dry_run_jobs' AND column_name=%s",
                    (column,),
                ).fetchone()
                if row and row["data_type"] == "timestamp without time zone":
                    db.execute(
                        f"ALTER TABLE mapping_dry_run_jobs ALTER COLUMN {column} "
                        f"TYPE TIMESTAMPTZ USING {column} AT TIME ZONE 'UTC'"
                    )

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
