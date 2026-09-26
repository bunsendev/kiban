"""Phase 3S-1 inventory foundationのPostgreSQL永続化。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .domain import canonical_datetime
from .job_contracts import (
    InventorySnapshotJobErrorCode,
    InventorySnapshotLease,
)
from .job_store import _aware_datetime
from .store import SqliteInventoryFoundationStore


class PostgresInventoryFoundationStore(SqliteInventoryFoundationStore):
    MIGRATION_LOCK_ID = 26092431

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

    def _initialize(self) -> None:
        statements = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8").split(";")
        with self._raw_connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (self.MIGRATION_LOCK_ID,))
            exists = db.execute(
                "SELECT to_regclass(current_schema() || '.inventory_snapshot_jobs') AS name"
            ).fetchone()["name"]
            if exists is not None:
                db.execute(
                    "ALTER TABLE inventory_snapshot_jobs "
                    "ADD COLUMN IF NOT EXISTS known_at TIMESTAMPTZ,"
                    "ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 0,"
                    "ADD COLUMN IF NOT EXISTS worker_id TEXT,"
                    "ADD COLUMN IF NOT EXISTS lease_token TEXT,"
                    "ADD COLUMN IF NOT EXISTS leased_until TIMESTAMPTZ,"
                    "ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ"
                )
                db.execute(
                    "UPDATE inventory_snapshot_jobs SET known_at=requested_at "
                    "WHERE known_at IS NULL"
                )
                db.execute(
                    "ALTER TABLE inventory_snapshot_jobs ALTER COLUMN known_at SET NOT NULL"
                )
                db.execute(
                    "UPDATE inventory_snapshot_jobs SET status='QUEUED',error_code=NULL "
                    "WHERE status='RUNNING' AND (worker_id IS NULL OR lease_token IS NULL "
                    "OR leased_until IS NULL)"
                )
                decision_exists = db.execute(
                    "SELECT to_regclass(current_schema() || "
                    "'.inventory_snapshot_decisions') AS name"
                ).fetchone()["name"]
                if decision_exists is not None:
                    db.execute(
                        "ALTER TABLE inventory_snapshot_decisions "
                        "ADD COLUMN IF NOT EXISTS revision INTEGER"
                    )
                    db.execute(
                        "WITH ranked AS (SELECT decision_id,ROW_NUMBER() OVER ("
                        "PARTITION BY COALESCE(snapshot_id,'job:' || job_id) "
                        "ORDER BY decided_at,decision_id) AS value "
                        "FROM inventory_snapshot_decisions) "
                        "UPDATE inventory_snapshot_decisions d SET revision=ranked.value "
                        "FROM ranked WHERE d.decision_id=ranked.decision_id "
                        "AND d.revision IS NULL"
                    )
                    db.execute(
                        "ALTER TABLE inventory_snapshot_decisions "
                        "ALTER COLUMN revision SET NOT NULL"
                    )
                    revision_constraint = db.execute(
                        "SELECT 1 FROM pg_constraint WHERE "
                        "conrelid='inventory_snapshot_decisions'::regclass "
                        "AND conname='inventory_snapshot_decisions_revision_check'"
                    ).fetchone()
                    if revision_constraint is None:
                        db.execute(
                            "ALTER TABLE inventory_snapshot_decisions ADD CONSTRAINT "
                            "inventory_snapshot_decisions_revision_check "
                            "CHECK(revision >= 1)"
                        )
            mapping_exists = db.execute(
                "SELECT to_regclass(current_schema() || "
                "'.inventory_input_mapping_versions') AS name"
            ).fetchone()["name"]
            if mapping_exists is not None:
                db.execute(
                    "ALTER TABLE inventory_input_mapping_versions "
                    "ADD COLUMN IF NOT EXISTS snapshot_at_source_kind "
                    "TEXT NOT NULL DEFAULT 'COLUMN',"
                    "ADD COLUMN IF NOT EXISTS snapshot_at_policy_version TEXT"
                )
            for statement in statements:
                if statement.strip():
                    db.execute(statement)
            mapping_source_constraint = db.execute(
                "SELECT 1 FROM pg_constraint WHERE "
                "conrelid='inventory_input_mapping_versions'::regclass "
                "AND conname='inventory_input_mapping_snapshot_source_check'"
            ).fetchone()
            if mapping_source_constraint is None:
                db.execute(
                    "ALTER TABLE inventory_input_mapping_versions ADD CONSTRAINT "
                    "inventory_input_mapping_snapshot_source_check CHECK("
                    "snapshot_at_source_kind IN ('COLUMN','FILENAME_YYYYMMDD'))"
                )
            mapping_policy_constraint = db.execute(
                "SELECT 1 FROM pg_constraint WHERE "
                "conrelid='inventory_input_mapping_versions'::regclass "
                "AND conname='inventory_input_mapping_snapshot_policy_check'"
            ).fetchone()
            if mapping_policy_constraint is None:
                db.execute(
                    "ALTER TABLE inventory_input_mapping_versions ADD CONSTRAINT "
                    "inventory_input_mapping_snapshot_policy_check CHECK("
                    "(snapshot_at_source_kind='COLUMN' AND "
                    "snapshot_at_policy_version IS NULL) OR "
                    "(snapshot_at_source_kind='FILENAME_YYYYMMDD' AND "
                    "snapshot_at_policy_version IS NOT NULL))"
                )
            constraint = db.execute(
                "SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                "WHERE conrelid='inventory_snapshot_quarantines'::regclass "
                "AND conname='inventory_snapshot_quarantines_reason_code_check'"
            ).fetchone()
            if constraint is None or "ROW_SHAPE_INVALID" not in constraint["definition"]:
                db.execute(
                    "ALTER TABLE inventory_snapshot_quarantines DROP CONSTRAINT IF EXISTS "
                    "inventory_snapshot_quarantines_reason_code_check"
                )
                db.execute(
                    "ALTER TABLE inventory_snapshot_quarantines ADD CONSTRAINT "
                    "inventory_snapshot_quarantines_reason_code_check CHECK(reason_code IN ("
                    "'ROW_SHAPE_INVALID','JAN_MISSING','JAN_INVALID',"
                    "'PRODUCT_MAPPING_MISSING','PRODUCT_MAPPING_AMBIGUOUS',"
                    "'LOCATION_MISSING','LOCATION_UNKNOWN','LOCATION_AMBIGUOUS',"
                    "'LOCATION_TYPE_INVALID','EXPIRY_MISSING','EXPIRY_INVALID',"
                    "'QUANTITY_MISSING','QUANTITY_INVALID','QUANTITY_NEGATIVE',"
                    "'SNAPSHOT_AT_MISSING','SNAPSHOT_AT_INVALID',"
                    "'SNAPSHOT_AT_INCONSISTENT','UNIT_MAPPING_MISSING',"
                    "'SOURCE_DUPLICATE','PDF_EXTRACTION_NOT_APPROVED'))"
                )

    def claim_next_job(
        self,
        worker_id: str,
        *,
        lease_seconds: int,
        now: datetime,
        max_attempts: int = 3,
    ) -> InventorySnapshotLease | None:
        if not worker_id.strip() or lease_seconds < 1 or max_attempts < 1:
            raise ValueError("worker_id、lease_seconds、max_attemptsが不正です")
        now = _aware_datetime(now, "now")
        leased_until = now + timedelta(seconds=lease_seconds)
        token = str(uuid.uuid4())
        with self._connect() as db:
            db.execute(
                "UPDATE inventory_snapshot_jobs SET status='FAILED',finished_at=?,"
                "error_code=?,worker_id=NULL,lease_token=NULL,leased_until=NULL "
                "WHERE status='RUNNING' AND leased_until<=? AND attempt>=?",
                (
                    canonical_datetime(now),
                    InventorySnapshotJobErrorCode.RETRY_EXHAUSTED.value,
                    canonical_datetime(now),
                    max_attempts,
                ),
            )
            row = db.execute(
                "SELECT job_id FROM inventory_snapshot_jobs "
                "WHERE status='QUEUED' OR (status='RUNNING' AND leased_until<=? AND attempt<?) "
                "ORDER BY requested_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1",
                (canonical_datetime(now), max_attempts),
            ).fetchone()
            if row is None:
                return None
            job_id = row[0]
            db.execute(
                "UPDATE inventory_snapshot_jobs SET status='RUNNING',"
                "started_at=COALESCE(started_at,?),finished_at=NULL,error_code=NULL,"
                "attempt=attempt+1,worker_id=?,lease_token=?,leased_until=?,"
                "last_heartbeat_at=? WHERE job_id=?",
                (
                    canonical_datetime(now),
                    worker_id,
                    token,
                    canonical_datetime(leased_until),
                    canonical_datetime(now),
                    job_id,
                ),
            )
        job = self.get_job(job_id)
        assert job is not None
        return InventorySnapshotLease(job, worker_id, token, leased_until)
