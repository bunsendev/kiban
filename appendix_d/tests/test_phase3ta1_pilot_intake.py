"""Phase 3T-A-1: Pilot対象だけをCSV原本から監査付きで取り込む。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from forecast_provider.inventory_forecast_bridge import (
    parse_confirmed_inventory_forecast_bridge_csv,
)
from forecast_provider.inventory_foundation import (
    InventoryInputMappingVersion,
    InventoryLocation,
    InventoryReferenceResolver,
    InventorySnapshotJobStatus,
    InventorySnapshotReadService,
    InventorySnapshotWorker,
    LocationMasterVersion,
    LocationType,
    NormalizedUnit,
    ProductIdentifierKind,
    SnapshotDecisionType,
    SqliteInventoryFoundationStore,
    create_inventory_snapshot_job,
)
from forecast_provider.pilot_gate_import import main as pilot_gate_main
from forecast_provider.pilot_scope import (
    SqlitePilotScopeStore,
    parse_confirmed_pilot_intake_csv,
    parse_confirmed_pilot_scope_csv,
)

NOW = datetime(2026, 9, 27, 8, tzinfo=UTC)


def _jan(index: int) -> str:
    body = f"49012345{index:04d}"
    weighted = sum(
        int(digit) * (3 if offset % 2 == 0 else 1) for offset, digit in enumerate(reversed(body))
    )
    return body + str((10 - weighted % 10) % 10)


class _Source:
    def __init__(self, content: bytes):
        self.content = content

    def read(self, _reference: str) -> bytes:
        return self.content


def _setup(tmp_path):
    path = tmp_path / "pilot.sqlite3"
    inventory = SqliteInventoryFoundationStore(path)
    pilots = SqlitePilotScopeStore(path)
    location_version = LocationMasterVersion("location-v1", "a" * 64, "tester", "fixture", NOW)
    warehouse = InventoryLocation(
        location_version.location_master_version,
        "warehouse-east",
        "W01",
        "人工倉庫",
        LocationType.WAREHOUSE,
        date(2026, 1, 1),
    )
    inventory.put_location_master(location_version, (warehouse,))
    mapping = InventoryInputMappingVersion(
        "pilot-mapping-v1",
        "JAN",
        ProductIdentifierKind.JAN,
        None,
        "拠点",
        location_version.location_master_version,
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
    inventory.put_mapping(mapping)
    scope_csv = (
        "JAN,warehouse_id,確認メモ\n"
        + "".join(f"{_jan(index)},warehouse-east,確認済み\n" for index in range(10))
    ).encode("utf-8-sig")
    scope = pilots.put(
        parse_confirmed_pilot_scope_csv(
            scope_csv,
            effective_from=NOW.date(),
            effective_to=NOW.date() + timedelta(days=30),
            approved_by="pilot-owner",
            reason="正式対象確認",
            created_at=NOW,
        )
    )
    intake_csv = (
        "原本商品値,原本拠点コード,JAN,warehouse_id,確認メモ\n"
        + "".join(
            f"{_jan(index)},W01,{_jan(index)},warehouse-east,確認済み\n" for index in range(10)
        )
    ).encode("utf-8-sig")
    intake = pilots.put_intake(
        parse_confirmed_pilot_intake_csv(
            intake_csv,
            scope=scope,
            mapping=mapping,
            resolver=InventoryReferenceResolver(mapping, (warehouse,)),
            created_by="pilot-owner",
            reason="原本列との対応確認",
            created_at=NOW,
        )
    )
    return inventory, pilots, mapping, scope, intake


def _enqueue(inventory, mapping, scope, intake, content):
    job = create_inventory_snapshot_job(
        source_reference="source/pilot-20260927.csv",
        source_sha256=hashlib.sha256(content).hexdigest(),
        mapping_version=mapping.mapping_version,
        requested_by="tester",
        known_at=NOW,
        requested_at=NOW,
        pilot_scope_version=scope.version.pilot_scope_version,
        pilot_intake_version=intake.intake_version,
    )
    return inventory.put_job(job)


def _csv(*rows):
    return ("JAN,拠点,賞味期限,明細バラ数,基準日時\n" + "".join(f"{row}\n" for row in rows)).encode(
        "utf-8-sig"
    )


def _all_scope_rows(*, first_expiry="2026-12-31"):
    return [
        f"{_jan(index)},W01,{first_expiry if index == 0 else '2026-12-31'},"
        f"{5 if index == 0 else 0},2026-09-27T08:00:00Z"
        for index in range(10)
    ]


def test_pilot_worker_preserves_outside_counts_and_hides_partial_snapshot_from_full_asof(tmp_path):
    inventory, pilots, mapping, scope, intake = _setup(tmp_path)
    content = _csv(
        *_all_scope_rows(),
        "UNMAPPED,W01,2026-12-31,7,2026-09-27T08:00:00Z",
    )
    job = _enqueue(inventory, mapping, scope, intake, content)
    result = InventorySnapshotWorker(
        inventory, _Source(content), pilot_scope_store=pilots, clock=lambda: NOW
    ).run_once("pilot-worker")

    assert result.status is InventorySnapshotJobStatus.SUCCEEDED
    assert (result.accepted_row_count, result.quarantined_row_count) == (10, 0)
    assert inventory.list_quarantines(job.job_id) == []
    audit = pilots.get_job_reconciliation(job.job_id)
    assert (
        audit["source_row_count"],
        audit["scoped_row_count"],
        audit["out_of_scope_row_count"],
    ) == (
        11,
        10,
        1,
    )
    assert (
        audit["source_quantity_cases"],
        audit["scoped_quantity_cases"],
        audit["out_of_scope_quantity_cases"],
    ) == (
        "12",
        "5",
        "7",
    )
    public_audit = InventorySnapshotReadService(inventory).reconciliation(job.job_id)
    assert public_audit["pilot_scope"]["out_of_scope_quantity_cases"] == "7"
    snapshot = inventory.list_snapshots(job.job_id)[0]
    assert snapshot["pilot_scope_version"] == scope.version.pilot_scope_version
    assert (
        pilots.get_scoped_snapshot(
            pilots.get_scoped_snapshot_id(
                snapshot["snapshot_id"], scope.version.pilot_scope_version
            )
        )
        is not None
    )
    inventory.append_snapshot_decision(
        job_id=job.job_id,
        snapshot_id=snapshot["snapshot_id"],
        decision=SnapshotDecisionType.APPROVED,
        decided_by="business-reviewer",
        reason="Pilot対象を確認",
        decided_at=NOW + timedelta(minutes=1),
    )
    assert inventory.find_approved_snapshot_as_of(NOW + timedelta(hours=1)) is None
    assert inventory.find_approved_snapshot_as_of(
        NOW + timedelta(hours=1), pilot_scope_version=scope.version.pilot_scope_version
    )["snapshot_id"] == snapshot["snapshot_id"]


def test_pilot_worker_quarantines_selected_errors_and_keeps_outside_audit(tmp_path):
    inventory, pilots, mapping, scope, intake = _setup(tmp_path)
    content = _csv(
        *_all_scope_rows(first_expiry=""),
        "UNMAPPED,W01,2026-12-31,7,2026-09-27T08:00:00Z",
    )
    job = _enqueue(inventory, mapping, scope, intake, content)
    result = InventorySnapshotWorker(
        inventory, _Source(content), pilot_scope_store=pilots, clock=lambda: NOW
    ).run_once("pilot-worker")

    assert result.status is InventorySnapshotJobStatus.SUCCEEDED
    assert inventory.list_snapshots(job.job_id) == []
    assert inventory.list_quarantines(job.job_id)[0]["reason_code"] == "EXPIRY_MISSING"
    audit = pilots.get_job_reconciliation(job.job_id)
    assert (audit["out_of_scope_row_count"], audit["quarantined_scope_row_count"]) == (1, 1)


def test_outside_unparseable_quantity_fails_closed(tmp_path):
    inventory, pilots, mapping, scope, intake = _setup(tmp_path)
    content = _csv(
        *_all_scope_rows(),
        "UNMAPPED,W01,2026-12-31,not-number,2026-09-27T08:00:00Z",
    )
    job = _enqueue(inventory, mapping, scope, intake, content)
    result = InventorySnapshotWorker(
        inventory, _Source(content), pilot_scope_store=pilots, clock=lambda: NOW
    ).run_once("pilot-worker")

    assert result.status is InventorySnapshotJobStatus.FAILED
    assert result.error_code == "OUT_OF_SCOPE_QUANTITY_UNRECONCILABLE"
    assert inventory.list_snapshots(job.job_id) == []


def test_missing_scope_target_is_not_accepted_as_zero_stock(tmp_path):
    inventory, pilots, mapping, scope, intake = _setup(tmp_path)
    content = _csv(*_all_scope_rows()[1:])
    job = _enqueue(inventory, mapping, scope, intake, content)
    result = InventorySnapshotWorker(
        inventory, _Source(content), pilot_scope_store=pilots, clock=lambda: NOW
    ).run_once("pilot-worker")
    assert result.status is InventorySnapshotJobStatus.FAILED
    assert result.error_code == "PILOT_SCOPE_INCOMPLETE"
    assert inventory.list_snapshots(job.job_id) == []


def test_unconfirmed_scope_and_identity_csv_are_rejected() -> None:
    with pytest.raises(ValueError, match="確認済み"):
        parse_confirmed_pilot_scope_csv(
            f"JAN,warehouse_id,確認メモ\n{_jan(0)},warehouse-east,未確認\n".encode(),
            effective_from=NOW.date(),
            effective_to=None,
            approved_by="owner",
            reason="fixture",
            created_at=NOW,
        )
    with pytest.raises(ValueError, match="確認済み"):
        parse_confirmed_inventory_forecast_bridge_csv(
            (
                "JAN,warehouse_id,canonical_product_id,forecast_center_id,"
                "effective_from,effective_to,確認メモ\n"
                f"{_jan(0)},warehouse-east,canonical-1,center-1,2026-09-27,,未確認\n"
            ).encode(),
            created_by="owner",
            reason="fixture",
            created_at=NOW,
        )


def test_pilot_gate_cli_registers_confirmed_contracts_and_enqueues(tmp_path, capsys):
    inventory, _pilots, mapping, scope, _intake = _setup(tmp_path)
    database = tmp_path / "pilot.sqlite3"
    scope_path = tmp_path / "scope.csv"
    scope_path.write_text(
        "JAN,warehouse_id,確認メモ\n"
        + "".join(f"{_jan(index)},warehouse-east,確認済み\n" for index in range(10)),
        encoding="utf-8-sig",
    )
    common = ["--sqlite", str(database)]
    assert pilot_gate_main(
        [*common,
            "scope", "--csv", str(scope_path), "--effective-from", "2026-09-27",
            "--effective-to", "2026-10-27", "--approved-by", "pilot-owner",
            "--reason", "正式対象確認",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["pilot_scope_version"] == (
        scope.version.pilot_scope_version
    )
    bridge_path = tmp_path / "bridge.csv"
    bridge_path.write_text(
        "JAN,warehouse_id,canonical_product_id,forecast_center_id,"
        "effective_from,effective_to,確認メモ\n"
        + "".join(
            f"{_jan(index)},warehouse-east,canonical-{index},center-east,"
            "2026-09-27,,確認済み\n"
            for index in range(10)
        ),
        encoding="utf-8-sig",
    )
    assert pilot_gate_main(
        [*common, "bridge", "--csv", str(bridge_path), "--created-by", "pilot-owner",
         "--reason", "予測接続確認"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["row_count"] == 10
    intake_path = tmp_path / "intake.csv"
    intake_path.write_text(
        "原本商品値,原本拠点コード,JAN,warehouse_id,確認メモ\n"
        + "".join(
            f"{_jan(index)},W01,{_jan(index)},warehouse-east,確認済み\n"
            for index in range(10)
        ),
        encoding="utf-8-sig",
    )
    assert pilot_gate_main(
        [*common,
            "intake", "--csv", str(intake_path), "--pilot-scope-version",
            scope.version.pilot_scope_version, "--mapping-version", mapping.mapping_version,
            "--created-by", "pilot-owner", "--reason", "原本列との対応確認",
        ]
    ) == 0
    intake_version = json.loads(capsys.readouterr().out)["pilot_intake_version"]
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "inventory.csv").write_bytes(
        _csv(f"{_jan(0)},W01,2026-12-31,5,2026-09-27T08:00:00Z")
    )
    assert pilot_gate_main(
        [*common,
            "enqueue", "--source-root", str(source_root), "--source-reference", "inventory.csv",
            "--pilot-scope-version", scope.version.pilot_scope_version,
            "--pilot-intake-version", intake_version,
            "--known-at", datetime.now(UTC).isoformat(),
            "--requested-by", "tester",
        ]
    ) == 0
    queued = json.loads(capsys.readouterr().out)
    assert inventory.get_job(queued["job_id"]).pilot_intake_version == intake_version
