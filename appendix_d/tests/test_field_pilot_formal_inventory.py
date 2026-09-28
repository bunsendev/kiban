"""承認済み在庫CSVだけ正式ジョブへ渡し、結果の先取り表示を防ぐ。"""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from forecast_provider.field_pilot import read_model
from forecast_provider.field_pilot.formal_inventory import FormalInventorySubmission
from forecast_provider.field_pilot.inbox_classifier import Classification, header_sha256
from forecast_provider.field_pilot.inbox_ledger import InboxLedger
from forecast_provider.field_pilot.inbox_policy import InboxPolicy, RequiredInput, SchemaRule
from forecast_provider.field_pilot.inbox_processor import InboxProcessor
from forecast_provider.field_pilot.read_model import FieldPilotReadService
from tests.test_field_pilot_unified_inbox import _stage


class Store:
    def __init__(self, item):
        self.item = item
        self.jobs = []

    def get_mapping(self, version):
        return self.item.mapping if version == "map-1" else None

    def get(self, version):
        return self.item.scope if version == "scope-1" else None

    def get_intake(self, version):
        return self.item.intake if version == "intake-1" else None

    def put_job(self, job):
        self.jobs.append(job)
        return job


def _setup(tmp_path):
    now = datetime(2026, 9, 28, tzinfo=UTC)
    item = SimpleNamespace(
        mapping=SimpleNamespace(mapping_version="map-1"),
        scope=SimpleNamespace(version=SimpleNamespace(
            pilot_scope_version="scope-1", created_at=now)),
        intake=SimpleNamespace(intake_version="intake-1", mapping_version="map-1",
                               pilot_scope_version="scope-1", created_at=now),
    )
    archive = tmp_path / "Archive"
    archive.mkdir()
    store = Store(item)
    adapter = FormalInventorySubmission(store, store, archive,
                                        clock=lambda: datetime(2026, 9, 29, tzinfo=UTC))
    return adapter, store, archive


def test_formal_inventory_requires_approved_contract_and_preserves_known_at(tmp_path):
    adapter, store, archive = _setup(tmp_path)
    content = b"day,warehouse,cases\n2026-09-28,EAST,4\n"
    digest = hashlib.sha256(content).hexdigest()
    path = archive / "stock.csv"
    path.write_bytes(content)
    valid = Classification("CONFIRMED", "KNOWN_SCHEMA", "WAREHOUSE_INVENTORY", "EAST",
                           "2026-09-28", "stock-v1", "map-1", "scope-1", "intake-1")
    assert adapter(valid, path, "stock.csv", digest).job_id
    assert len(store.jobs) == 1
    assert store.jobs[0].source_sha256 == digest
    assert store.jobs[0].pilot_scope_version == "scope-1"
    assert store.jobs[0].known_at == datetime(2026, 9, 29, tzinfo=UTC)
    missing = Classification("CONFIRMED", "KNOWN_SCHEMA", "WAREHOUSE_INVENTORY", "EAST",
                             "2026-09-28", "stock-v1", "missing", "scope-1", "intake-1")
    assert adapter(missing, path, "stock.csv", digest) is False
    assert adapter(valid, path, "../stock.csv", digest) is False
    shipment = Classification("CONFIRMED", "KNOWN_SCHEMA", "SHIPMENT_ACTUAL", "EAST",
                              "2026-09-28", "stock-v1", "map-1", "scope-1", "intake-1")
    assert adapter(shipment, path, "stock.csv", digest) is False
    assert len(store.jobs) == 1


def test_queued_formal_job_does_not_mark_inbox_ready(tmp_path):
    root = tmp_path / "Inbox"
    root.mkdir()
    headers = ("day", "warehouse", "cases")
    policy = InboxPolicy("v1", (RequiredInput("WAREHOUSE_INVENTORY", "EAST", "東倉庫"),), (
        SchemaRule("stock-v1", "WAREHOUSE_INVENTORY", "EAST", header_sha256(headers),
                   headers, "day", "%Y-%m-%d", "cases", "warehouse", "map-1",
                   "scope-1", "intake-1"),
    ))
    ledger = InboxLedger(root / "inbox.sqlite3")
    adapter, store, _ = _setup(root)
    _stage(root, "stock.csv", b"day,warehouse,cases\n2026-09-28,EAST,4\n")
    InboxProcessor(root, policy, ledger, validated_import=adapter).scan()
    summary = ledger.summary(policy, "2026-09-28")
    assert summary["status"] != "READY"
    assert summary["required"][0]["status"] == "RECEIVED"
    assert len(store.jobs) == 1


def test_formal_inventory_status_requires_explicit_snapshot_approval(tmp_path):
    root = tmp_path / "Inbox"
    root.mkdir()
    ledger = InboxLedger(root / "inbox.sqlite3")
    day = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    policy_path = tmp_path / "inbox-policy.json"
    policy_path.write_text(json.dumps({
        "format": "field-pilot-inbox-v1", "version": "v1",
        "required": [{"kind": "WAREHOUSE_INVENTORY", "location_id": "EAST",
                      "display_name": "東倉庫"}],
        "rules": [{"schema_id": "stock-v1", "kind": "WAREHOUSE_INVENTORY",
                   "location_id": "EAST", "header_sha256": "a" * 64,
                   "required_columns": ["day"], "date_column": "day",
                   "date_format": "%Y-%m-%d"}],
    }), encoding="utf-8")
    classification = Classification("CONFIRMED", "KNOWN_SCHEMA", "WAREHOUSE_INVENTORY",
                                    "EAST", day, "stock-v1", "map-1")
    ledger.record(stage_id="a" * 32, sha256="b" * 64,
                  source_name_sha256="c" * 64, size_bytes=10,
                  status="RECEIVED", reason="INVENTORY_JOB_QUEUED",
                  classification=classification, policy_version="v1",
                  archive_reference="bb/id/file.csv", received_at=datetime.now(UTC).isoformat(),
                  formal_job_id="job-1")

    class FormalStore:
        decision = None

        def get_job(self, job_id):
            assert job_id == "job-1"
            return SimpleNamespace(status="SUCCEEDED", accepted_row_count=1,
                                   quarantined_row_count=0, source_sha256="b" * 64,
                                   mapping_version="map-1")

        def list_snapshots(self, job_id):
            return [{"snapshot_id": "snapshot-1"}]

        def get_reconciliation(self, job_id):
            return {"reconciled": True, "source_quantity_cases": "4",
                    "normalized_quantity_cases": "4"}

        def get_latest_snapshot_decision(self, snapshot_id):
            return self.decision

    formal = FormalStore()
    service = FieldPilotReadService(None, tmp_path / "settings.json", policy_path, root,
                                    inventory_store=formal)
    pending = service.inbox_view()
    assert pending["status"] != "READY"
    assert pending["formal_jobs"][0]["status"] == "APPROVAL_REQUIRED"
    formal.decision = {"decision": "APPROVED"}
    approved = service.inbox_view()
    assert approved["status"] == "READY"
    assert approved["approved_count"] == 1

    ledger.record(stage_id="d" * 32, sha256="e" * 64,
                  source_name_sha256="f" * 64, size_bytes=10,
                  status="RECEIVED", reason="INVENTORY_JOB_QUEUED",
                  classification=classification, policy_version="v1",
                  archive_reference="ee/id/file.csv",
                  received_at=datetime.now(UTC).isoformat(), formal_job_id="job-2")
    original_get_job = formal.get_job

    def get_job(job_id):
        if job_id == "job-2":
            return SimpleNamespace(status="QUEUED", accepted_row_count=0,
                                   quarantined_row_count=0, source_sha256="e" * 64,
                                   mapping_version="map-1")
        return original_get_job(job_id)

    formal.get_job = get_job
    newer = service.inbox_view()
    assert newer["status"] != "READY"
    assert newer["required"][0]["status"] == "RECEIVED"


def test_formal_approval_requires_latest_reconciled_zero_quarantine(tmp_path, monkeypatch):
    root = tmp_path / "Inbox"
    root.mkdir()
    ledger = InboxLedger(root / "inbox.sqlite3")
    classification = Classification("CONFIRMED", "KNOWN_SCHEMA", "WAREHOUSE_INVENTORY",
                                    "EAST", "2026-09-28", "stock-v1", "map-1")
    ledger.record(stage_id="a" * 32, sha256="b" * 64,
                  source_name_sha256="c" * 64, size_bytes=10,
                  status="RECEIVED", reason="INVENTORY_JOB_QUEUED",
                  classification=classification, policy_version="v1",
                  archive_reference="bb/id/file.csv",
                  received_at=datetime.now(UTC).isoformat(), formal_job_id="job-1")

    class FormalStore:
        quarantined = 0

        def get_job(self, job_id):
            return SimpleNamespace(status="SUCCEEDED", source_sha256="b" * 64,
                                   mapping_version="map-1",
                                   quarantined_row_count=self.quarantined)

        def list_snapshots(self, job_id):
            return [{"snapshot_id": "snapshot-1"}]

        def get_reconciliation(self, job_id):
            return {"reconciled": True}

    calls = []

    class DecisionService:
        def __init__(self, store):
            pass

        def append_decision(self, **kwargs):
            calls.append(kwargs)
            return {"decision": kwargs["decision"]}

    monkeypatch.setattr(read_model, "InventorySnapshotReadService", DecisionService)
    store = FormalStore()
    service = FieldPilotReadService(None, tmp_path / "settings.json", inbox_root=root,
                                    inventory_store=store)
    store.quarantined = 1
    with pytest.raises(ValueError, match="NOT_READY"):
        service.approve_formal_inventory("job-1", actor="admin", reason="checked",
                                         expected_revision=0)
    store.quarantined = 0
    assert service.approve_formal_inventory("job-1", actor="admin", reason="checked",
                                            expected_revision=0) == {"decision": "APPROVED"}
    assert calls[0]["snapshot_id"] == "snapshot-1"
    ledger.record(stage_id="d" * 32, sha256="e" * 64,
                  source_name_sha256="f" * 64, size_bytes=10,
                  status="RECEIVED", reason="INVENTORY_JOB_QUEUED",
                  classification=classification, policy_version="v1",
                  archive_reference="ee/id/file.csv",
                  received_at=datetime.now(UTC).isoformat(), formal_job_id="job-2")
    with pytest.raises(ValueError, match="NOT_READY"):
        service.approve_formal_inventory("job-1", actor="admin", reason="checked",
                                         expected_revision=0)
