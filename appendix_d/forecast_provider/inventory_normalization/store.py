"""在庫正規化jobと日次残高のSQLite/PostgreSQL台帳。"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..jobs.postgres_store import _Connection


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteInventoryNormalizationStore:
    def __init__(self, path: Path):
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    def enqueue(self, source_prefix, product_mapping_id, unit_value, requested_by):
        job_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute(
                "INSERT INTO inventory_normalization_jobs("
                "job_id,source_prefix,product_mapping_id,unit_value,requested_by,"
                "status,requested_at) "
                "VALUES (?,?,?,?,?,'QUEUED',?)",
                (job_id, source_prefix, product_mapping_id, unit_value, requested_by, _now()),
            )
        return job_id

    def get(self, job_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM inventory_normalization_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["reason_counts"] = json.loads(value.pop("reason_counts_json"))
        return value

    def claim(self):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT job_id FROM inventory_normalization_jobs WHERE status='QUEUED' "
                "ORDER BY requested_at,rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            job_id = row[0]
            db.execute(
                "UPDATE inventory_normalization_jobs SET status='RUNNING',started_at=? "
                "WHERE job_id=?",
                (_now(), job_id),
            )
        return self.get(job_id)

    def progress(self, job_id, file_count, processed, accepted, quarantined, reasons):
        with self._connect() as db:
            db.execute(
                "UPDATE inventory_normalization_jobs SET file_count=?,processed_file_count=?,"
                "accepted_row_count=?,quarantined_row_count=?,reason_counts_json=? WHERE job_id=?",
                (
                    file_count,
                    processed,
                    accepted,
                    quarantined,
                    json.dumps(reasons, sort_keys=True),
                    job_id,
                ),
            )

    def complete(self, job_id, values):
        with self._connect() as db:
            db.execute("BEGIN")
            db.executemany(
                "INSERT INTO inventory_daily_quantities VALUES (?,?,?,?,?,?)",
                [(job_id, *value) for value in values],
            )
            db.execute(
                "UPDATE inventory_normalization_jobs SET status='SUCCEEDED',finished_at=? "
                "WHERE job_id=?",
                (_now(), job_id),
            )

    def fail(self, job_id, error_code):
        with self._connect() as db:
            db.execute(
                "UPDATE inventory_normalization_jobs SET status='FAILED',"
                "error_code=?,finished_at=? "
                "WHERE job_id=?",
                (error_code, _now(), job_id),
            )

    def list_values(self, job_id):
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT inventory_date,jan,center_id,unit,quantity "
                    "FROM inventory_daily_quantities "
                    "WHERE job_id=? ORDER BY inventory_date,jan,center_id,unit",
                    (job_id,),
                )
            ]


class PostgresInventoryNormalizationStore(SqliteInventoryNormalizationStore):
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
            db.execute("SELECT pg_advisory_xact_lock(26091601)")
            for statement in (
                Path(__file__).with_name("schema.sql").read_text(encoding="utf-8").split(";")
            ):
                if statement.strip():
                    db.execute(statement)

    def claim(self):
        with self._connect() as db:
            row = db.execute(
                "SELECT job_id FROM inventory_normalization_jobs WHERE status='QUEUED' "
                "ORDER BY requested_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            job_id = row[0]
            db.execute(
                "UPDATE inventory_normalization_jobs SET status='RUNNING',started_at=? "
                "WHERE job_id=?",
                (_now(), job_id),
            )
        return self.get(job_id)
