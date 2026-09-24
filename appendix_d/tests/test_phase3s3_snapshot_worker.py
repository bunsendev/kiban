"""Phase 3S-3: snapshot job、transaction、lease、独立Worker。"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from forecast_provider.inventory_foundation import (
    DirectoryInventorySourceReader,
    InventoryInputMappingVersion,
    InventoryLocation,
    InventoryReferenceResolver,
    InventorySnapshotJobErrorCode,
    InventorySnapshotJobStatus,
    InventorySnapshotService,
    InventorySnapshotWorker,
    InventorySourceReadError,
    LocationMasterVersion,
    LocationType,
    NormalizedUnit,
    PostgresInventoryFoundationStore,
    ProductIdentifierKind,
    SnapshotDecisionType,
    SqliteInventoryFoundationStore,
    StaleInventorySnapshotLeaseError,
    create_inventory_snapshot_job,
)

NOW = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
VALID_JAN = "4901234567894"


class MemorySourceReader:
    def __init__(self, values: dict[str, bytes]):
        self.values = values

    def read(self, source_reference: str) -> bytes:
        return self.values[source_reference]


def _mapping(suffix: str = "1") -> InventoryInputMappingVersion:
    return InventoryInputMappingVersion(
        f"inventory-map-v{suffix}",
        "JAN",
        ProductIdentifierKind.JAN,
        None,
        "拠点",
        f"locations-v{suffix}",
        "賞味期限",
        "明細バラ数",
        "基準日時",
        "明細バラ数",
        "箱",
        NormalizedUnit.CASE,
        "utf-8-sig",
        ",",
        1,
        "tester",
        "fixture",
        NOW,
    )


def _prepare_store(path: Path, suffix: str = "1"):
    store = SqliteInventoryFoundationStore(path)
    version = LocationMasterVersion(
        f"locations-v{suffix}", "a" * 64, "tester", "fixture", NOW
    )
    locations = (
        InventoryLocation(
            version.location_master_version,
            f"factory-{suffix}",
            "F01",
            "人工工場",
            LocationType.FACTORY,
            date(2026, 1, 1),
        ),
        InventoryLocation(
            version.location_master_version,
            f"warehouse-{suffix}",
            "W01",
            "人工倉庫",
            LocationType.WAREHOUSE,
            date(2026, 1, 1),
        ),
    )
    mapping = _mapping(suffix)
    store.put_location_master(version, locations)
    store.put_mapping(mapping)
    return store, mapping, locations


def _csv(*rows: str) -> bytes:
    text = "JAN,拠点,賞味期限,明細バラ数,基準日時\n" + "\n".join(rows) + "\n"
    return text.encode("utf-8-sig")


def _enqueue(store, mapping, content, reference="source/artificial.csv"):
    job = create_inventory_snapshot_job(
        source_reference=reference,
        source_sha256=hashlib.sha256(content).hexdigest(),
        mapping_version=mapping.mapping_version,
        requested_by="tester",
        requested_at=NOW,
    )
    return store.put_job(job)


def _valid_content(quantity="3"):
    return _csv(
        f"{VALID_JAN},W01,2026-12-31,{quantity},2026-09-24T08:00:00Z"
    )


def test_worker_approves_valid_csv_in_one_transaction(tmp_path):
    store, mapping, _ = _prepare_store(tmp_path / "approved.sqlite3")
    content = _valid_content()
    queued = _enqueue(store, mapping, content)
    worker = InventorySnapshotWorker(
        store,
        MemorySourceReader({queued.source_reference: content}),
        clock=lambda: NOW,
    )

    completed = worker.run_once("worker-1")

    assert completed.status is InventorySnapshotJobStatus.SUCCEEDED
    assert completed.accepted_row_count == 1
    assert completed.quarantined_row_count == 0
    decision = store.list_decisions(queued.job_id)[0]
    assert decision["decision"] == SnapshotDecisionType.APPROVED.value
    assert decision["snapshot_id"].startswith("inventory-snapshot-")
    assert store.list_expiry_buckets(decision["snapshot_id"])[0]["quantity_cases"] == "3"
    assert store.get_reconciliation(queued.job_id)["reconciled"] == 1


def test_worker_records_rejected_input_without_partial_snapshot(tmp_path):
    store, mapping, _ = _prepare_store(tmp_path / "rejected.sqlite3")
    content = _csv(f"{VALID_JAN},W01,,5,2026-09-24T08:00:00Z")
    queued = _enqueue(store, mapping, content)
    worker = InventorySnapshotWorker(
        store,
        MemorySourceReader({queued.source_reference: content}),
        clock=lambda: NOW,
    )

    completed = worker.run_once("worker-1")

    assert completed.status is InventorySnapshotJobStatus.SUCCEEDED
    assert completed.accepted_row_count == 0
    assert completed.quarantined_row_count == 1
    assert store.list_decisions(queued.job_id)[0]["decision"] == "REJECTED"
    assert store.list_decisions(queued.job_id)[0]["snapshot_id"] is None
    assert store.list_quarantines(queued.job_id)[0]["reason_code"] == "EXPIRY_MISSING"
    reconciliation = store.get_reconciliation(queued.job_id)
    assert reconciliation["source_quantity_cases"] == "5"
    assert reconciliation["normalized_quantity_cases"] == "0"
    assert reconciliation["reconciled"] == 0
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM inventory_snapshots").fetchone()[0] == 0


def test_job_registration_is_content_addressed_and_idempotent(tmp_path):
    store, mapping, _ = _prepare_store(tmp_path / "idempotent.sqlite3")
    content = _valid_content()
    first = _enqueue(store, mapping, content)
    second = _enqueue(store, mapping, content)
    assert first.job_id == second.job_id
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM inventory_snapshot_jobs").fetchone()[0] == 1


def test_hash_mismatch_fails_without_persisting_raw_input(tmp_path):
    store, mapping, _ = _prepare_store(tmp_path / "hash.sqlite3")
    expected = _valid_content("1")
    actual = _valid_content("999999")
    queued = _enqueue(store, mapping, expected)
    worker = InventorySnapshotWorker(
        store,
        MemorySourceReader({queued.source_reference: actual}),
        clock=lambda: NOW,
    )
    completed = worker.run_once("worker-1")
    assert completed.status is InventorySnapshotJobStatus.FAILED
    assert completed.error_code == InventorySnapshotJobErrorCode.SOURCE_SHA256_MISMATCH.value
    assert "999999" not in repr(completed)
    assert not store.list_decisions(queued.job_id)
    assert store.get_reconciliation(queued.job_id) is None


def test_expired_lease_is_reclaimed_and_old_worker_is_fenced(tmp_path):
    store, mapping, locations = _prepare_store(tmp_path / "lease.sqlite3")
    content = _valid_content()
    _enqueue(store, mapping, content)
    first = store.claim_next_job("worker-old", lease_seconds=30, now=NOW)
    assert first.job.attempt == 1
    second = store.claim_next_job(
        "worker-new", lease_seconds=30, now=NOW + timedelta(seconds=31)
    )
    assert second.job.attempt == 2
    with pytest.raises(StaleInventorySnapshotLeaseError):
        store.heartbeat(first, lease_seconds=30, now=NOW + timedelta(seconds=31))

    resolver = InventoryReferenceResolver(mapping, locations)
    value = InventorySnapshotService().prepare_finalization(
        first,
        content,
        mapping,
        resolver,
        completed_at=NOW + timedelta(seconds=31),
    )
    with pytest.raises(StaleInventorySnapshotLeaseError):
        store.finalize_job(first, value)


def test_heartbeat_extends_active_lease(tmp_path):
    store, mapping, _ = _prepare_store(tmp_path / "heartbeat.sqlite3")
    _enqueue(store, mapping, _valid_content())
    lease = store.claim_next_job("worker-1", lease_seconds=30, now=NOW)
    extended = store.heartbeat(
        lease,
        lease_seconds=60,
        now=NOW + timedelta(seconds=20),
    )
    assert extended.leased_until == NOW + timedelta(seconds=80)
    assert extended.job.last_heartbeat_at == NOW + timedelta(seconds=20)


def test_unexpected_worker_failure_requeues_without_error_details(tmp_path):
    store, mapping, _ = _prepare_store(tmp_path / "retry.sqlite3")
    queued = _enqueue(store, mapping, _valid_content())

    class BrokenReader:
        def read(self, source_reference):
            raise RuntimeError("sensitive runtime detail")

    completed = InventorySnapshotWorker(store, BrokenReader(), clock=lambda: NOW).run_once(
        "worker-1"
    )
    assert completed.status is InventorySnapshotJobStatus.QUEUED
    assert completed.error_code == InventorySnapshotJobErrorCode.INTERNAL_ERROR.value
    assert "sensitive" not in repr(completed)
    assert completed.attempt == 1
    assert completed.worker_id is None
    assert completed.lease_token is None
    assert not store.list_decisions(queued.job_id)


def test_retryable_failure_stops_after_three_fenced_attempts(tmp_path):
    store, mapping, _ = _prepare_store(tmp_path / "retry-limit.sqlite3")
    queued = _enqueue(store, mapping, _valid_content())

    class BrokenReader:
        def read(self, source_reference):
            raise RuntimeError("artificial failure")

    worker = InventorySnapshotWorker(store, BrokenReader(), clock=lambda: NOW)
    assert worker.run_once("worker-1").status is InventorySnapshotJobStatus.QUEUED
    assert worker.run_once("worker-2").status is InventorySnapshotJobStatus.QUEUED
    completed = worker.run_once("worker-3")
    assert completed.status is InventorySnapshotJobStatus.FAILED
    assert completed.attempt == 3
    assert completed.error_code == InventorySnapshotJobErrorCode.INTERNAL_ERROR.value
    assert not store.list_decisions(queued.job_id)


def test_csv_contract_failure_is_non_retryable_and_safe(tmp_path):
    store, mapping, _ = _prepare_store(tmp_path / "contract.sqlite3")
    content = b"\xff"
    queued = _enqueue(store, mapping, content)
    completed = InventorySnapshotWorker(
        store,
        MemorySourceReader({queued.source_reference: content}),
        clock=lambda: NOW,
    ).run_once("worker-1")
    assert completed.status is InventorySnapshotJobStatus.FAILED
    assert completed.error_code == InventorySnapshotJobErrorCode.CSV_CONTRACT_FAILED.value
    assert completed.attempt == 1


def test_finalize_rollback_removes_snapshot_and_derived_rows(tmp_path):
    class FailingStore(SqliteInventoryFoundationStore):
        @staticmethod
        def _insert_snapshot(db, value, *, job_id):
            SqliteInventoryFoundationStore._insert_snapshot(db, value, job_id=job_id)
            raise RuntimeError("artificial failure")

    path = tmp_path / "rollback.sqlite3"
    base, mapping, locations = _prepare_store(path)
    del base
    store = FailingStore(path)
    content = _valid_content()
    queued = _enqueue(store, mapping, content)
    worker = InventorySnapshotWorker(store, MemorySourceReader({queued.source_reference: content}))
    completed = worker.run_once("worker-1")
    assert completed.status is InventorySnapshotJobStatus.QUEUED
    with sqlite3.connect(path) as db:
        for table in (
            "inventory_snapshots",
            "inventory_expiry_buckets",
            "inventory_snapshot_reconciliations",
            "inventory_snapshot_decisions",
        ):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert locations


def test_retry_uses_stable_known_at_and_snapshot_identity(tmp_path):
    store, mapping, locations = _prepare_store(tmp_path / "identity.sqlite3")
    content = _valid_content()
    _enqueue(store, mapping, content)
    lease = store.claim_next_job("worker-1", lease_seconds=300, now=NOW)
    resolver = InventoryReferenceResolver(mapping, locations)
    service = InventorySnapshotService()
    first = service.prepare_finalization(
        lease, content, mapping, resolver, completed_at=NOW + timedelta(seconds=1)
    )
    second = service.prepare_finalization(
        lease, content, mapping, resolver, completed_at=NOW + timedelta(hours=1)
    )
    assert first.snapshot.header.snapshot_id == second.snapshot.header.snapshot_id
    assert first.decision_id == second.decision_id
    assert first.snapshot.header.known_at == NOW


def test_directory_reader_confines_references_and_size(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    (root / "ok.csv").write_bytes(b"1234")
    reader = DirectoryInventorySourceReader(root, max_bytes=4)
    assert reader.read("ok.csv") == b"1234"
    with pytest.raises(InventorySourceReadError) as traversal:
        reader.read("../outside.csv")
    assert traversal.value.code is InventorySnapshotJobErrorCode.SOURCE_REFERENCE_INVALID
    (root / "large.csv").write_bytes(b"12345")
    with pytest.raises(InventorySourceReadError) as large:
        reader.read("large.csv")
    assert large.value.code is InventorySnapshotJobErrorCode.SOURCE_TOO_LARGE


def test_phase3s1_sqlite_schema_is_upgraded_without_losing_rows(tmp_path):
    path = tmp_path / "upgrade.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE inventory_snapshot_jobs("
            "job_id TEXT PRIMARY KEY,source_kind TEXT NOT NULL,source_reference TEXT NOT NULL,"
            "source_sha256 TEXT NOT NULL,mapping_version TEXT NOT NULL,requested_by TEXT NOT NULL,"
            "status TEXT NOT NULL,accepted_row_count INTEGER NOT NULL DEFAULT 0,"
            "quarantined_row_count INTEGER NOT NULL DEFAULT 0,error_code TEXT,"
            "requested_at TEXT NOT NULL,started_at TEXT,finished_at TEXT);"
            "CREATE TABLE inventory_snapshot_quarantines("
            "quarantine_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,source_reference TEXT NOT NULL,"
            "row_number INTEGER NOT NULL,row_sha256 TEXT NOT NULL,"
            "reason_code TEXT NOT NULL CHECK(reason_code IN ('JAN_MISSING')),"
            "created_at TEXT NOT NULL);"
            "INSERT INTO inventory_snapshot_jobs VALUES("
            "'old','CSV','old.csv','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
            "'old-map','tester','QUEUED',0,0,NULL,'2026-09-24T08:00:00+00:00',NULL,NULL);"
            "INSERT INTO inventory_snapshot_quarantines VALUES("
            "'old-q','old','old.csv',1,"
            "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',"
            "'JAN_MISSING','2026-09-24T08:00:00+00:00');"
        )
    store = SqliteInventoryFoundationStore(path)
    with sqlite3.connect(path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(inventory_snapshot_jobs)")}
        assert {"attempt", "worker_id", "lease_token", "leased_until"}.issubset(columns)
        assert db.execute(
            "SELECT reason_code FROM inventory_snapshot_quarantines"
        ).fetchone()[0] == "JAN_MISSING"
        db.execute(
            "INSERT INTO inventory_snapshot_quarantines VALUES(?,?,?,?,?,?,?)",
            (
                "new-q",
                "old",
                "old.csv",
                2,
                "c" * 64,
                "ROW_SHAPE_INVALID",
                NOW.isoformat(),
            ),
        )
    assert store.get_job("old").attempt == 0


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_snapshot_worker_matches_sqlite_transaction_contract():
    suffix = uuid.uuid4().hex
    store = PostgresInventoryFoundationStore(os.environ["KIBAN_TEST_POSTGRES_DSN"])
    version = LocationMasterVersion(
        f"locations-v{suffix}", "d" * 64, "tester", "fixture", NOW
    )
    location = InventoryLocation(
        version.location_master_version,
        f"warehouse-{suffix}",
        "W01",
        "人工倉庫",
        LocationType.WAREHOUSE,
        date(2026, 1, 1),
    )
    mapping = _mapping(suffix)
    store.put_location_master(version, (location,))
    store.put_mapping(mapping)
    content = _valid_content()
    job = _enqueue(store, mapping, content, f"source/{suffix}.csv")
    completed = InventorySnapshotWorker(
        store,
        MemorySourceReader({job.source_reference: content}),
        clock=lambda: NOW,
    ).run_once(f"worker-{suffix}")
    assert completed.status is InventorySnapshotJobStatus.SUCCEEDED
    assert store.list_decisions(job.job_id)[0]["decision"] == "APPROVED"
