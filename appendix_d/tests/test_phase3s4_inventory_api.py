"""Phase 3S-4 API / Read Modelの人工データ結合試験。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.api.security import TokenAuthenticator
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.inventory_foundation import (
    InventoryDecisionConflict,
    InventoryInputMappingVersion,
    InventoryLocation,
    InventorySnapshotWorker,
    LocationMasterVersion,
    LocationType,
    NormalizedUnit,
    PostgresInventoryFoundationStore,
    ProductIdentifierKind,
    SnapshotDecisionType,
    SqliteInventoryFoundationStore,
    create_inventory_snapshot_job,
)
from forecast_provider.jobs import SqliteRunStore

NOW = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
JAN = "4901234567894"
TOKENS = {
    "viewer": "viewer-token-00000000000000000000",
    "analyst": "analyst-token-0000000000000000000",
    "approver": "approver-token-000000000000000000",
}


class MemorySourceReader:
    def __init__(self, values):
        self.values = values

    def read(self, source_reference):
        return self.values[source_reference]


def _headers(role: str, **extra) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[role]}", **extra}


def _app(tmp_path):
    database = tmp_path / "phase3s4.sqlite3"
    inventory = SqliteInventoryFoundationStore(database)
    location_version = LocationMasterVersion(
        "locations-v1", "a" * 64, "test", "artificial", NOW
    )
    inventory.put_location_master(
        location_version,
        (
            InventoryLocation(
                "locations-v1", "factory-1", "F01", "人工工場", LocationType.FACTORY,
                date(2026, 1, 1),
            ),
            InventoryLocation(
                "locations-v1", "warehouse-1", "W01", "人工倉庫", LocationType.WAREHOUSE,
                date(2026, 1, 1),
            ),
            InventoryLocation(
                "locations-v1", "warehouse-2", "W02", "人工倉庫2", LocationType.WAREHOUSE,
                date(2026, 1, 1),
            ),
        ),
    )
    mapping = InventoryInputMappingVersion(
        "inventory-map-v1", "JAN", ProductIdentifierKind.JAN, None, "拠点",
        "locations-v1", "賞味期限", "明細バラ数", "基準日時", "明細バラ数", "箱",
        NormalizedUnit.CASE, "utf-8-sig", ",", 1, "test", "artificial", NOW,
    )
    inventory.put_mapping(mapping)
    credentials = [
        {"token": token, "subject": f"{role}@example.test", "roles": [role.upper()]}
        for role, token in TOKENS.items()
    ]
    app = create_app(
        SqliteRunStore(database),
        SqliteCatalogStore(database),
        TokenAuthenticator.from_json(json.dumps(credentials)),
        inventory_foundation=inventory,
    )
    return TestClient(app), inventory, mapping


def _csv(*rows: str) -> bytes:
    return (
        "JAN,拠点,賞味期限,明細バラ数,基準日時\n" + "\n".join(rows) + "\n"
    ).encode("utf-8-sig")


def _process(inventory, mapping, content: bytes, *, known_at=NOW, reference="artificial.csv"):
    job = inventory.put_job(
        create_inventory_snapshot_job(
            source_reference=reference,
            source_sha256=hashlib.sha256(content).hexdigest(),
            mapping_version=mapping.mapping_version,
            requested_by="analyst@example.test",
            known_at=known_at,
            requested_at=known_at,
        )
    )
    InventorySnapshotWorker(
        inventory,
        MemorySourceReader({reference: content}),
        clock=lambda: known_at + timedelta(minutes=1),
    ).run_once("test-worker")
    snapshots = inventory.list_snapshots(job.job_id)
    return job, None if not snapshots else snapshots[0]["snapshot_id"]


def _valid(snapshot_at="2026-09-24T08:00:00Z"):
    return _csv(f"{JAN},W01,2026-12-31,3,{snapshot_at}")


def test_job_registration_is_authorized_idempotent_and_does_not_expose_path(tmp_path):
    api, _inventory, mapping = _app(tmp_path)
    payload = {
        "source_reference": "private/operator/path.csv",
        "source_sha256": hashlib.sha256(b"artificial").hexdigest(),
        "mapping_version": mapping.mapping_version,
        "known_at": NOW.isoformat(),
    }
    assert api.post(
        "/api/inventory-snapshot-jobs", json=payload, headers=_headers("viewer")
    ).status_code == 403
    headers = _headers("analyst", **{"Idempotency-Key": "phase3s4-register-1"})
    first = api.post("/api/inventory-snapshot-jobs", json=payload, headers=headers)
    second = api.post("/api/inventory-snapshot-jobs", json=payload, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert "source_reference" not in first.json()
    missing = api.post(
        "/api/inventory-snapshot-jobs",
        json={**payload, "mapping_version": "missing"},
        headers=_headers("analyst"),
    )
    assert (missing.status_code, missing.json()["code"]) == (
        404,
        "INVENTORY_MAPPING_NOT_FOUND",
    )
    not_found = api.get(
        "/api/inventory-snapshot-jobs/missing", headers=_headers("viewer")
    )
    assert (not_found.status_code, not_found.json()["code"]) == (
        404,
        "INVENTORY_JOB_NOT_FOUND",
    )


def test_status_quarantine_summary_and_reconciliation_hide_raw_values(tmp_path):
    api, inventory, mapping = _app(tmp_path)
    content = _csv(f"{JAN},W01,,999999,2026-09-24T08:00:00Z")
    job, snapshot_id = _process(inventory, mapping, content)
    assert snapshot_id is None
    status = api.get(
        f"/api/inventory-snapshot-jobs/{job.job_id}", headers=_headers("viewer")
    )
    assert status.json()["status"] == "SUCCEEDED"
    assert status.json()["attempt"] == 1
    assert "source_reference" not in status.json()
    summary = api.get(
        f"/api/inventory-snapshot-jobs/{job.job_id}/quarantine-summary",
        headers=_headers("analyst"),
    )
    assert summary.json()["items"] == [{"reason_code": "EXPIRY_MISSING", "row_count": 1}]
    assert "999999" not in summary.text
    reconciliation = api.get(
        f"/api/inventory-snapshot-jobs/{job.job_id}/reconciliation",
        headers=_headers("analyst"),
    ).json()
    assert reconciliation["source_quantity"] == "999999"
    assert reconciliation["normalized_quantity"] == "0"
    assert reconciliation["difference"] == "-999999"
    assert reconciliation["matched"] is False
    assert reconciliation["normalized_unit"] == "CASE"


def test_approval_is_append_only_role_guarded_and_revision_checked(tmp_path):
    api, inventory, mapping = _app(tmp_path)
    job, snapshot_id = _process(inventory, mapping, _valid())
    assert snapshot_id
    unapproved = api.get(
        f"/api/inventory-snapshots/{snapshot_id}/fefo", headers=_headers("viewer")
    )
    assert (unapproved.status_code, unapproved.json()["code"]) == (
        409,
        "INVENTORY_SNAPSHOT_NOT_APPROVED",
    )
    endpoint = f"/api/inventory-snapshots/{snapshot_id}/decisions"
    assert api.post(
        endpoint,
        json={"decision": "APPROVED", "expected_revision": 0},
        headers=_headers("analyst"),
    ).status_code == 403
    approved = api.post(
        endpoint,
        json={"decision": "APPROVED", "expected_revision": 0},
        headers=_headers("approver"),
    )
    assert approved.status_code == 201
    assert approved.json()["revision"] == 1
    assert approved.json()["decided_by"] == "approver@example.test"
    conflict = api.post(
        endpoint,
        json={"decision": "REJECTED", "expected_revision": 0, "reason": "stale"},
        headers=_headers("approver"),
    )
    assert (conflict.status_code, conflict.json()["code"]) == (
        409,
        "INVENTORY_DECISION_CONFLICT",
    )
    rejected = api.post(
        endpoint,
        json={"decision": "REJECTED", "expected_revision": 1, "reason": "業務確認"},
        headers=_headers("approver"),
    )
    assert rejected.json()["revision"] == 2
    history = api.get(endpoint, headers=_headers("viewer")).json()["items"]
    assert [item["decision"] for item in history] == ["APPROVED", "REJECTED"]
    detail = api.get(
        f"/api/inventory-snapshots/{snapshot_id}", headers=_headers("viewer")
    ).json()
    assert detail["current_decision"]["decision"] == "REJECTED"
    assert detail["job_id"] == job.job_id


def test_approved_as_of_prevents_future_leakage_and_rejection_removes_snapshot(tmp_path):
    api, inventory, mapping = _app(tmp_path)
    old_content = _csv(
        f"{JAN},W02,2026-09-01,1,2026-09-23T08:00:00Z",
        f"{JAN},W01,2026-10-01,2,2026-09-23T08:00:00Z",
        f"{JAN},W01,2026-11-01,3,2026-09-23T08:00:00Z",
    )
    old_job, old_id = _process(
        inventory, mapping, old_content, known_at=datetime(2026, 9, 24, tzinfo=UTC),
        reference="old.csv",
    )
    new_job, new_id = _process(
        inventory,
        mapping,
        _valid("2026-09-25T08:00:00Z"),
        known_at=datetime(2026, 9, 25, 9, tzinfo=UTC),
        reference="new.csv",
    )
    inventory.append_snapshot_decision(
        job_id=old_job.job_id,
        snapshot_id=old_id,
        decision=SnapshotDecisionType.APPROVED,
        decided_by="approver",
        reason="old approved",
        decided_at=datetime(2026, 9, 24, 1, tzinfo=UTC),
        expected_revision=0,
    )
    inventory.append_snapshot_decision(
        job_id=new_job.job_id,
        snapshot_id=new_id,
        decision=SnapshotDecisionType.APPROVED,
        decided_by="approver",
        reason="new approved",
        decided_at=datetime(2026, 9, 25, 10, tzinfo=UTC),
        expected_revision=0,
    )
    endpoint = "/api/inventory-snapshots/approved/as-of"
    past = api.get(
        endpoint,
        params={"calculation_at": "2026-09-24T12:00:00Z"},
        headers=_headers("viewer"),
    )
    assert past.status_code == 200
    assert past.json()["snapshot"]["snapshot_id"] == old_id
    items = past.json()["items"]
    assert [(item["location_id"], item["expiry_date"]) for item in items] == [
        ("warehouse-1", "2026-10-01"),
        ("warehouse-1", "2026-11-01"),
        ("warehouse-2", "2026-09-01"),
    ]
    assert items[-1]["expired_at_snapshot"] is True
    current = api.get(
        endpoint,
        params={"calculation_at": "2026-09-26T00:00:00Z"},
        headers=_headers("viewer"),
    )
    assert current.json()["snapshot"]["snapshot_id"] == new_id
    inventory.append_snapshot_decision(
        job_id=new_job.job_id,
        snapshot_id=new_id,
        decision=SnapshotDecisionType.REJECTED,
        decided_by="approver",
        reason="late rejection",
        decided_at=datetime(2026, 9, 26, 12, tzinfo=UTC),
        expected_revision=1,
    )
    after_rejection = api.get(
        endpoint,
        params={"calculation_at": "2026-09-27T00:00:00Z"},
        headers=_headers("viewer"),
    )
    assert after_rejection.json()["snapshot"]["snapshot_id"] == old_id


def test_snapshot_and_fefo_pagination_and_filters_are_stable(tmp_path):
    api, inventory, mapping = _app(tmp_path)
    job, snapshot_id = _process(
        inventory,
        mapping,
        _csv(
            f"{JAN},W01,2026-10-01,1,2026-09-24T08:00:00Z",
            f"{JAN},W01,2026-11-01,2,2026-09-24T08:00:00Z",
            f"{JAN},W02,2026-12-01,3,2026-09-24T08:00:00Z",
        ),
    )
    inventory.append_snapshot_decision(
        job_id=job.job_id,
        snapshot_id=snapshot_id,
        decision=SnapshotDecisionType.APPROVED,
        decided_by="approver",
        reason="approved",
        decided_at=NOW + timedelta(hours=1),
        expected_revision=0,
    )
    snapshots = api.get(
        "/api/inventory-snapshots",
        params={"limit": 1, "offset": 0, "decision_status": "APPROVED"},
        headers=_headers("viewer"),
    ).json()
    assert (snapshots["total"], len(snapshots["items"])) == (1, 1)
    page = api.get(
        f"/api/inventory-snapshots/{snapshot_id}/fefo",
        params={"limit": 1, "offset": 1, "location_id": "warehouse-1"},
        headers=_headers("viewer"),
    ).json()
    assert page["total"] == 2
    assert page["items"][0]["expiry_date"] == "2026-11-01"


def test_inventory_operations_use_structured_audit_without_business_rows(tmp_path, caplog):
    api, _inventory, mapping = _app(tmp_path)
    payload = {
        "source_reference": "private/artificial.csv",
        "source_sha256": "b" * 64,
        "mapping_version": mapping.mapping_version,
        "known_at": NOW.isoformat(),
    }
    with caplog.at_level(logging.INFO, logger="kiban.audit"):
        response = api.post(
            "/api/inventory-snapshot-jobs", json=payload, headers=_headers("analyst")
        )
    assert response.status_code == 202
    records = [json.loads(record.message) for record in caplog.records]
    audit = next(
        value
        for value in records
        if value.get("operation") == "INVENTORY_SNAPSHOT_JOB_REGISTERED"
    )
    assert audit["audit"] is True
    assert audit["subject"] == "analyst@example.test"
    assert "private/artificial.csv" not in json.dumps(audit)


def _postgres_setup():
    suffix = uuid.uuid4().hex
    store = PostgresInventoryFoundationStore(os.environ["KIBAN_TEST_POSTGRES_DSN"])
    with store._raw_connect() as connection:
        connection.execute("TRUNCATE inventory_location_master_versions CASCADE")
    version = LocationMasterVersion(
        f"locations-{suffix}", hashlib.sha256(suffix.encode()).hexdigest(),
        "test", "artificial", NOW,
    )
    store.put_location_master(
        version,
        (
            InventoryLocation(
                version.location_master_version, f"factory-{suffix}", "F01", "人工工場",
                LocationType.FACTORY, date(2026, 1, 1),
            ),
            InventoryLocation(
                version.location_master_version, f"warehouse-{suffix}", "W01", "人工倉庫",
                LocationType.WAREHOUSE, date(2026, 1, 1),
            ),
        ),
    )
    mapping = InventoryInputMappingVersion(
        f"mapping-{suffix}", "JAN", ProductIdentifierKind.JAN, None, "拠点",
        version.location_master_version, "賞味期限", "明細バラ数", "基準日時",
        "明細バラ数", "箱", NormalizedUnit.CASE, "utf-8-sig", ",", 1,
        "test", "artificial", NOW,
    )
    store.put_mapping(mapping)
    return store, mapping, suffix


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_pagination_indexes_as_of_and_expiry_sort():
    store, mapping, suffix = _postgres_setup()
    content = _csv(
        f"{JAN},W01,2026-10-01,1,2026-09-24T08:00:00Z",
        f"{JAN},W01,2026-11-01,2,2026-09-24T08:00:00Z",
        f"{JAN},W01,2026-12-01,3,2026-09-24T08:00:00Z",
    )
    job, snapshot_id = _process(
        store, mapping, content, reference=f"artificial/{suffix}.csv"
    )
    store.append_snapshot_decision(
        job_id=job.job_id,
        snapshot_id=snapshot_id,
        decision=SnapshotDecisionType.APPROVED,
        decided_by="approver",
        reason="artificial",
        decided_at=NOW + timedelta(hours=1),
        expected_revision=0,
    )
    total, snapshots = store.list_snapshots_page(
        limit=1, offset=0, decision_status="APPROVED"
    )
    assert total >= 1
    assert snapshots[0]["current_decision"] == "APPROVED"
    selected = store.find_approved_snapshot_as_of(NOW + timedelta(hours=2), jan=JAN)
    assert selected["snapshot_id"] == snapshot_id
    bucket_total, buckets = store.list_expiry_buckets_page(
        snapshot_id, limit=2, offset=1, jan=JAN
    )
    assert bucket_total == 3
    assert [row["expiry_date"] for row in buckets] == ["2026-11-01", "2026-12-01"]
    with store._raw_connect() as connection:
        indexes = {
            row["indexname"]
            for row in connection.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname=current_schema() "
                "AND tablename IN ('inventory_snapshots','inventory_expiry_buckets',"
                "'inventory_snapshot_decisions')"
            ).fetchall()
        }
    assert {
        "inventory_snapshots_as_of_idx",
        "inventory_expiry_buckets_fefo_idx",
        "inventory_snapshot_decisions_revision_idx",
        "inventory_snapshot_decisions_state_idx",
    }.issubset(indexes)


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_decision_revision_conflict_is_not_silent():
    store, mapping, suffix = _postgres_setup()
    job, snapshot_id = _process(
        store, mapping, _valid(), reference=f"artificial/concurrency-{suffix}.csv"
    )

    def approve(subject):
        try:
            return store.append_snapshot_decision(
                job_id=job.job_id,
                snapshot_id=snapshot_id,
                decision=SnapshotDecisionType.APPROVED,
                decided_by=subject,
                reason="concurrency",
                decided_at=NOW + timedelta(hours=1),
                expected_revision=0,
            )
        except InventoryDecisionConflict:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, ("approver-a", "approver-b")))
    assert sum(value == "CONFLICT" for value in results) == 1
    assert len(store.list_snapshot_decisions(snapshot_id)) == 1
