"""inventory snapshot job、lease、finalizationのSQLite/PostgreSQL共通操作。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from .contracts import SnapshotDecisionType, SourceKind
from .domain import canonical_datetime, canonical_decimal
from .job_contracts import (
    InventorySnapshotFinalization,
    InventorySnapshotJob,
    InventorySnapshotJobErrorCode,
    InventorySnapshotJobStatus,
    InventorySnapshotLease,
    StaleInventorySnapshotLeaseError,
)


class InventorySnapshotJobStoreMixin:
    def put_job(self, value: InventorySnapshotJob) -> InventorySnapshotJob:
        with self._connect() as db:
            db.execute(
                "INSERT INTO inventory_snapshot_jobs("
                "job_id,source_kind,source_reference,source_sha256,mapping_version,"
                "requested_by,status,accepted_row_count,quarantined_row_count,error_code,"
                "known_at,requested_at,started_at,finished_at,attempt,worker_id,lease_token,"
                "leased_until,last_heartbeat_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(job_id) DO NOTHING",
                _job_values(value),
            )
        stored = self.get_job(value.job_id)
        if stored is None:
            raise RuntimeError("inventory snapshot jobを保存できません")
        expected = (
            value.source_kind,
            value.source_reference,
            value.source_sha256,
            value.mapping_version,
            value.known_at,
        )
        actual = (
            stored.source_kind,
            stored.source_reference,
            stored.source_sha256,
            stored.mapping_version,
            stored.known_at,
        )
        if actual != expected:
            raise ValueError("同じjob IDに異なる入力は登録できません")
        return stored

    def get_job(self, job_id: str) -> InventorySnapshotJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM inventory_snapshot_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return None if row is None else _snapshot_job(row)

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
            db.execute("BEGIN IMMEDIATE")
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
                "ORDER BY requested_at,job_id LIMIT 1",
                (canonical_datetime(now), max_attempts),
            ).fetchone()
            if row is None:
                return None
            job_id = row[0]
            changed = db.execute(
                "UPDATE inventory_snapshot_jobs SET status='RUNNING',"
                "started_at=COALESCE(started_at,?),finished_at=NULL,error_code=NULL,"
                "attempt=attempt+1,worker_id=?,lease_token=?,leased_until=?,"
                "last_heartbeat_at=? WHERE job_id=? AND "
                "(status='QUEUED' OR (status='RUNNING' AND leased_until<=?))",
                (
                    canonical_datetime(now),
                    worker_id,
                    token,
                    canonical_datetime(leased_until),
                    canonical_datetime(now),
                    job_id,
                    canonical_datetime(now),
                ),
            ).rowcount
            if changed != 1:
                return None
        job = self.get_job(job_id)
        assert job is not None
        return InventorySnapshotLease(job, worker_id, token, leased_until)

    def heartbeat(
        self,
        lease: InventorySnapshotLease,
        *,
        lease_seconds: int,
        now: datetime,
    ) -> InventorySnapshotLease:
        if lease_seconds < 1:
            raise ValueError("lease_secondsは正数です")
        now = _aware_datetime(now, "now")
        leased_until = now + timedelta(seconds=lease_seconds)
        with self._connect() as db:
            changed = db.execute(
                "UPDATE inventory_snapshot_jobs SET leased_until=?,last_heartbeat_at=? "
                "WHERE job_id=? AND status='RUNNING' AND attempt=? AND worker_id=? "
                "AND lease_token=? AND leased_until>?",
                (
                    canonical_datetime(leased_until),
                    canonical_datetime(now),
                    lease.job.job_id,
                    lease.job.attempt,
                    lease.worker_id,
                    lease.lease_token,
                    canonical_datetime(now),
                ),
            ).rowcount
        if changed != 1:
            raise StaleInventorySnapshotLeaseError("inventory snapshot leaseは失効しています")
        job = self.get_job(lease.job.job_id)
        assert job is not None
        return InventorySnapshotLease(job, lease.worker_id, lease.lease_token, leased_until)

    def fail_job(
        self,
        lease: InventorySnapshotLease,
        error_code: InventorySnapshotJobErrorCode,
        *,
        retryable: bool,
        now: datetime,
        max_attempts: int = 3,
    ) -> None:
        now = _aware_datetime(now, "now")
        next_status = (
            InventorySnapshotJobStatus.QUEUED
            if retryable and lease.job.attempt < max_attempts
            else InventorySnapshotJobStatus.FAILED
        )
        finished_at = None if next_status is InventorySnapshotJobStatus.QUEUED else now
        with self._connect() as db:
            changed = db.execute(
                "UPDATE inventory_snapshot_jobs SET status=?,finished_at=?,error_code=?,"
                "worker_id=NULL,lease_token=NULL,leased_until=NULL "
                "WHERE job_id=? AND status='RUNNING' AND attempt=? "
                "AND worker_id=? AND lease_token=?",
                (
                    next_status.value,
                    None if finished_at is None else canonical_datetime(finished_at),
                    error_code.value,
                    lease.job.job_id,
                    lease.job.attempt,
                    lease.worker_id,
                    lease.lease_token,
                ),
            ).rowcount
        if changed != 1:
            raise StaleInventorySnapshotLeaseError("inventory snapshot leaseは失効しています")

    def finalize_job(
        self,
        lease: InventorySnapshotLease,
        value: InventorySnapshotFinalization,
    ) -> None:
        job = lease.job
        validation = value.validation
        if validation.source_sha256 != job.source_sha256:
            raise ValueError("validationとjobのsource SHA-256が一致しません")
        if validation.mapping_version != job.mapping_version:
            raise ValueError("validationとjobのmapping versionが一致しません")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_active_lease(db, lease, value.completed_at)
            snapshot_id = None
            if value.snapshot is not None:
                snapshot_id = value.snapshot.header.snapshot_id
                self._insert_snapshot(db, value.snapshot, job_id=job.job_id)
            for quarantine in validation.quarantines:
                for reason in quarantine.reasons:
                    quarantine_id = _stable_id(
                        "inventory-quarantine",
                        job.job_id,
                        str(quarantine.row_number),
                        reason.value,
                    )
                    db.execute(
                        "INSERT INTO inventory_snapshot_quarantines VALUES (?,?,?,?,?,?,?)",
                        (
                            quarantine_id,
                            job.job_id,
                            job.source_reference,
                            quarantine.row_number,
                            quarantine.row_sha256,
                            reason.value,
                            canonical_datetime(value.completed_at),
                        ),
                    )
            reconciliation = validation.reconciliation
            db.execute(
                "INSERT INTO inventory_snapshot_reconciliations VALUES (?,?,?,?,?,?)",
                (
                    _stable_id("inventory-reconciliation", job.job_id),
                    job.job_id,
                    canonical_decimal(reconciliation.source_quantity_cases),
                    canonical_decimal(reconciliation.normalized_quantity_cases),
                    int(reconciliation.reconciled),
                    canonical_datetime(value.completed_at),
                ),
            )
            if value.decision is not None:
                db.execute(
                    "INSERT INTO inventory_snapshot_decisions VALUES (?,?,?,?,?,?,?,?)",
                    (
                        value.decision_id,
                        job.job_id,
                        snapshot_id,
                        value.decision_version,
                        value.decision.value,
                        value.decided_by,
                        value.reason,
                        canonical_datetime(value.decided_at),
                    ),
                )
            changed = db.execute(
                "UPDATE inventory_snapshot_jobs SET status='SUCCEEDED',"
                "accepted_row_count=?,quarantined_row_count=?,error_code=NULL,finished_at=?,"
                "worker_id=NULL,lease_token=NULL,leased_until=NULL "
                "WHERE job_id=? AND status='RUNNING' AND attempt=? "
                "AND worker_id=? AND lease_token=?",
                (
                    reconciliation.accepted_row_count,
                    reconciliation.quarantined_row_count,
                    canonical_datetime(value.completed_at),
                    job.job_id,
                    job.attempt,
                    lease.worker_id,
                    lease.lease_token,
                ),
            ).rowcount
            if changed != 1:
                raise StaleInventorySnapshotLeaseError(
                    "inventory snapshot leaseは失効しています"
                )

    @staticmethod
    def _require_active_lease(db, lease: InventorySnapshotLease, now: datetime) -> None:
        row = db.execute(
            "SELECT 1 FROM inventory_snapshot_jobs WHERE job_id=? AND status='RUNNING' "
            "AND attempt=? AND worker_id=? AND lease_token=? AND leased_until>?",
            (
                lease.job.job_id,
                lease.job.attempt,
                lease.worker_id,
                lease.lease_token,
                canonical_datetime(now),
            ),
        ).fetchone()
        if row is None:
            raise StaleInventorySnapshotLeaseError("inventory snapshot leaseは失効しています")

    def list_quarantines(self, job_id: str) -> list[dict]:
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT quarantine_id,row_number,row_sha256,reason_code,created_at "
                    "FROM inventory_snapshot_quarantines WHERE job_id=? "
                    "ORDER BY row_number,reason_code",
                    (job_id,),
                )
            ]

    def get_reconciliation(self, job_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT source_quantity_cases,normalized_quantity_cases,reconciled,created_at "
                "FROM inventory_snapshot_reconciliations WHERE job_id=?",
                (job_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def list_decisions(self, job_id: str) -> list[dict]:
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT decision_id,snapshot_id,decision_version,decision,decided_by,"
                    "reason,decided_at FROM inventory_snapshot_decisions WHERE job_id=? "
                    "ORDER BY decided_at,decision_id",
                    (job_id,),
                )
            ]

    def append_snapshot_decision(
        self,
        *,
        job_id: str,
        snapshot_id: str,
        decision: SnapshotDecisionType,
        decided_by: str,
        reason: str,
        decided_at: datetime,
    ) -> dict:
        if not isinstance(decision, SnapshotDecisionType):
            raise ValueError("decisionが不正です")
        if not decided_by.strip() or not reason.strip():
            raise ValueError("decided_byとreasonは必須です")
        decided_at = _aware_datetime(decided_at, "decided_at")
        decision_id = _stable_id(
            "inventory-decision",
            job_id,
            snapshot_id,
            decision.value,
            decided_by,
            reason,
            canonical_datetime(decided_at),
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT 1 FROM inventory_snapshots s "
                "JOIN inventory_snapshot_jobs j ON j.job_id=s.job_id "
                "WHERE s.snapshot_id=? AND s.job_id=? AND j.status='SUCCEEDED'",
                (snapshot_id, job_id),
            ).fetchone()
            if row is None:
                raise ValueError("技術的生成が完了したsnapshotだけを判断できます")
            db.execute(
                "INSERT INTO inventory_snapshot_decisions VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(decision_id) DO NOTHING",
                (
                    decision_id,
                    job_id,
                    snapshot_id,
                    decision_id,
                    decision.value,
                    decided_by,
                    reason,
                    canonical_datetime(decided_at),
                ),
            )
        return next(
            value for value in self.list_decisions(job_id) if value["decision_id"] == decision_id
        )


def _aware_datetime(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label}はtimezone付き日時です")
    return value.astimezone(UTC)


def _datetime(value) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_datetime(value) -> datetime | None:
    return None if value is None else _datetime(value)


def _job_values(value: InventorySnapshotJob) -> tuple:
    return (
        value.job_id,
        value.source_kind.value,
        value.source_reference,
        value.source_sha256,
        value.mapping_version,
        value.requested_by,
        value.status.value,
        value.accepted_row_count,
        value.quarantined_row_count,
        value.error_code,
        canonical_datetime(value.known_at),
        canonical_datetime(value.requested_at),
        None if value.started_at is None else canonical_datetime(value.started_at),
        None if value.finished_at is None else canonical_datetime(value.finished_at),
        value.attempt,
        value.worker_id,
        value.lease_token,
        None if value.leased_until is None else canonical_datetime(value.leased_until),
        None
        if value.last_heartbeat_at is None
        else canonical_datetime(value.last_heartbeat_at),
    )


def _snapshot_job(row) -> InventorySnapshotJob:
    return InventorySnapshotJob(
        row["job_id"],
        SourceKind(row["source_kind"]),
        row["source_reference"],
        row["source_sha256"],
        row["mapping_version"],
        row["requested_by"],
        InventorySnapshotJobStatus(row["status"]),
        row["accepted_row_count"],
        row["quarantined_row_count"],
        row["error_code"],
        _datetime(row["known_at"]),
        _datetime(row["requested_at"]),
        _optional_datetime(row["started_at"]),
        _optional_datetime(row["finished_at"]),
        row["attempt"],
        row["worker_id"],
        row["lease_token"],
        _optional_datetime(row["leased_until"]),
        _optional_datetime(row["last_heartbeat_at"]),
    )


def _stable_id(prefix: str, *parts: str) -> str:
    encoded = json.dumps(parts, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()}"

