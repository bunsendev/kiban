"""在庫正規化jobと日次残高のSQLite/PostgreSQL台帳。"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .features import InventoryFeatureViewMixin


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _same_quantity(left, right) -> bool:
    try:
        return Decimal(left) == Decimal(right)
    except (InvalidOperation, TypeError):
        return False


class SqliteInventoryNormalizationStore(InventoryFeatureViewMixin):
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

    def list_jobs(self, limit=100):
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM inventory_normalization_jobs "
                "ORDER BY requested_at DESC,job_id DESC LIMIT ?",
                (limit,),
            )
            values = [dict(row) for row in rows]
        for value in values:
            value["reason_counts"] = json.loads(value.pop("reason_counts_json"))
        return values

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

    def complete(self, job_id, values, source_quantity, normalized_quantity):
        with self._connect() as db:
            db.execute("BEGIN")
            db.executemany(
                "INSERT INTO inventory_daily_quantities VALUES (?,?,?,?,?,?)",
                [(job_id, *value) for value in values],
            )
            db.execute(
                "INSERT INTO inventory_normalization_summaries VALUES (?,?,?)",
                (job_id, source_quantity, normalized_quantity),
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

    def results(self, job_id, limit, offset):
        with self._connect() as db:
            summary = db.execute(
                "SELECT source_quantity,normalized_quantity "
                "FROM inventory_normalization_summaries WHERE job_id=?",
                (job_id,),
            ).fetchone()
            count = db.execute(
                "SELECT COUNT(*) FROM inventory_daily_quantities WHERE job_id=?",
                (job_id,),
            ).fetchone()[0]
            rows = db.execute(
                "SELECT inventory_date,jan,center_id,unit,quantity "
                "FROM inventory_daily_quantities WHERE job_id=? "
                "ORDER BY inventory_date,jan,center_id,unit LIMIT ? OFFSET ?",
                (job_id, limit, offset),
            )
            items = [dict(row) for row in rows]
        if summary is None:
            return None
        summary = dict(summary)
        return {
            **summary,
            "reconciled": _same_quantity(
                summary["source_quantity"], summary["normalized_quantity"]
            ),
            "total": count,
            "limit": limit,
            "offset": offset,
            "items": items,
        }

    def decide(self, job_id, decision_version, decision, decided_by, reason):
        if not all((job_id, decision_version, decision, decided_by, reason)):
            raise ValueError("判断版・判断・担当者・理由は必須です")
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("判断が不正です")
        decision_id = str(uuid.uuid4())
        with self._connect() as db:
            row = db.execute(
                "SELECT j.status,j.quarantined_row_count,s.source_quantity,"
                "s.normalized_quantity FROM inventory_normalization_jobs j "
                "LEFT JOIN inventory_normalization_summaries s ON s.job_id=j.job_id "
                "WHERE j.job_id=?",
                (job_id,),
            ).fetchone()
            if row is None or row["status"] != "SUCCEEDED":
                raise ValueError("完了した在庫正規化jobだけを判断できます")
            if decision == "APPROVED":
                reconciled = _same_quantity(
                    row["source_quantity"], row["normalized_quantity"]
                )
                if not reconciled or row["quarantined_row_count"] != 0:
                    raise ValueError("数量一致かつ隔離0行のjobだけを採用できます")
            existing = db.execute(
                "SELECT decision_id FROM inventory_normalization_decisions "
                "WHERE decision_version=?",
                (decision_version,),
            ).fetchone()
            if existing is not None:
                raise ValueError("同じdecision versionは再利用できません")
            db.execute(
                "INSERT INTO inventory_normalization_decisions VALUES (?,?,?,?,?,?,?)",
                (
                    decision_id,
                    job_id,
                    decision_version,
                    decision,
                    decided_by,
                    reason,
                    _now(),
                ),
            )
        return decision_id

    def list_decisions(self, job_id=None):
        sql = "SELECT * FROM inventory_normalization_decisions"
        params = ()
        if job_id is not None:
            sql += " WHERE job_id=?"
            params = (job_id,)
        sql += " ORDER BY decided_at,decision_id"
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, params)]

    def current_adoption(self):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM inventory_normalization_decisions "
                "WHERE decision='APPROVED' ORDER BY decided_at DESC,decision_id DESC LIMIT 1"
            ).fetchone()
        return None if row is None else dict(row)


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
