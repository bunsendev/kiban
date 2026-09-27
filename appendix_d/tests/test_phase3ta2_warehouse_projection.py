"""Phase 3T-A: 承認済みPilot在庫と確定予測の14日Projection。"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from forecast_provider.inventory_forecast_bridge import (
    SqliteInventoryForecastBridgeStore,
    build_inventory_forecast_bridge,
)
from forecast_provider.inventory_foundation import (
    InventorySnapshotWorker,
    SnapshotDecisionType,
)
from forecast_provider.jobs import (
    Expectation,
    ForecastValue,
    OriginDefinition,
    OriginOutput,
    RunDefinition,
    SqliteRunStore,
)
from forecast_provider.warehouse_projection import (
    ProjectionBlocked,
    WarehouseProjectionService,
    build_warehouse_projection,
)
from forecast_provider.warehouse_projection.cli import main as projection_main
from tests.test_phase3ta1_pilot_intake import (
    NOW,
    _all_scope_rows,
    _csv,
    _enqueue,
    _jan,
    _setup,
    _Source,
)


def _ready(tmp_path, *, horizon=14):
    inventory, pilots, mapping, scope, intake = _setup(tmp_path)
    content = _csv(*_all_scope_rows())
    job = _enqueue(inventory, mapping, scope, intake, content)
    InventorySnapshotWorker(
        inventory, _Source(content), pilot_scope_store=pilots, clock=lambda: NOW
    ).run_once("worker")
    snapshot_id = inventory.list_snapshots(job.job_id)[0]["snapshot_id"]
    inventory.append_snapshot_decision(
        job_id=job.job_id, snapshot_id=snapshot_id,
        decision=SnapshotDecisionType.APPROVED, decided_by="reviewer",
        reason="Pilot確認", decided_at=NOW + timedelta(minutes=1),
    )
    bridges = SqliteInventoryForecastBridgeStore(tmp_path / "pilot.sqlite3")
    bridge = bridges.put(
        build_inventory_forecast_bridge(
            records=[
                (_jan(index), "warehouse-east", f"canonical-{index}", "center-east",
                 NOW.date(), None)
                for index in range(10)
            ],
            created_by="reviewer", reason="identity確認", created_at=NOW,
        )
    )
    runs = SqliteRunStore(tmp_path / "pilot.sqlite3")
    origin = NOW.date()
    expectations = tuple(
        Expectation(f"canonical-{index}::center-east", origin,
                    origin + timedelta(days=day), day)
        for index in range(10) for day in range(1, horizon + 1)
    )
    runs.create_run(
        RunDefinition("run-pilot", "experiment-pilot", "condition-pilot",
                      "builtin-baseline", "baseline", 7),
        (OriginDefinition(origin, NOW + timedelta(hours=1)),), expectations,
    )
    runs.start_or_resume("run-pilot", "condition-pilot")
    lease = runs.claim_next_origin("run-pilot", "worker", 60)
    values = tuple(
        ForecastValue(
            f"canonical-{index}::center-east", origin, origin + timedelta(days=day),
            day, "POINT", None, Decimal("1"), Decimal("1"),
        )
        for index in range(10) for day in range(1, horizon + 1)
    )
    runs.complete_origin(lease, OriginOutput(values))
    assert runs.finish_run("run-pilot") == "SUCCEEDED"
    service = WarehouseProjectionService(inventory, pilots, bridges, runs)
    return service, scope, bridge, inventory, snapshot_id


def test_approved_projection_is_deterministic_and_preserves_shortage(tmp_path):
    service, scope, bridge, _inventory, snapshot_id = _ready(tmp_path)
    calculation_at = datetime.now(UTC) + timedelta(minutes=1)
    arguments = {
        "calculation_at": calculation_at,
        "pilot_scope_version": scope.version.pilot_scope_version,
        "identity_bridge_version": bridge.version.bridge_version,
        "forecast_run_id": "run-pilot",
    }
    first = service.calculate(**arguments)
    again = service.calculate(**arguments)
    assert first == again
    assert first.inventory_snapshot_id == snapshot_id
    assert len(first.projections) == 10
    item = next(value for value in first.projections if value.jan == _jan(0))
    assert (item.starting_inventory_cases, item.demand_7_days_cases,
            item.demand_14_days_cases) == (Decimal("5"), Decimal("7"), Decimal("14"))
    assert item.first_shortage_date == date(2026, 10, 3)
    assert item.days[5].cumulative_shortfall_cases == Decimal("1")
    assert item.days[-1].gross_remaining_cases == Decimal("-9")


def test_incomplete_horizon_and_future_run_are_blocked(tmp_path):
    service, scope, bridge, _inventory, _snapshot_id = _ready(tmp_path, horizon=7)
    args = {
        "pilot_scope_version": scope.version.pilot_scope_version,
        "identity_bridge_version": bridge.version.bridge_version,
        "forecast_run_id": "run-pilot",
    }
    with pytest.raises(ProjectionBlocked, match="FORECAST_RUN_NOT_AVAILABLE_AS_OF"):
        service.calculate(calculation_at=NOW + timedelta(minutes=2), **args)
    with pytest.raises(ProjectionBlocked, match="FORECAST_HORIZON_INCOMPLETE"):
        service.calculate(calculation_at=datetime.now(UTC) + timedelta(minutes=1), **args)


def test_withdrawn_business_approval_blocks_projection(tmp_path):
    service, scope, bridge, inventory, snapshot_id = _ready(tmp_path)
    job_id = inventory.get_snapshot(snapshot_id)["job_id"]
    inventory.append_snapshot_decision(
        job_id=job_id, snapshot_id=snapshot_id,
        decision=SnapshotDecisionType.REJECTED, decided_by="reviewer",
        reason="在庫訂正待ち", decided_at=NOW + timedelta(minutes=2),
    )
    with pytest.raises(ProjectionBlocked, match="APPROVED_PILOT_SNAPSHOT_NOT_FOUND"):
        service.calculate(
            calculation_at=datetime.now(UTC) + timedelta(minutes=1),
            pilot_scope_version=scope.version.pilot_scope_version,
            identity_bridge_version=bridge.version.bridge_version,
            forecast_run_id="run-pilot",
        )


def test_projection_rejects_missing_day_negative_demand_and_float():
    days = tuple((date(2026, 9, 28) + timedelta(days=i), "1") for i in range(14))
    arguments = {
        "jan": _jan(0), "warehouse_id": "warehouse-east",
        "starting_inventory_cases": "5", "forecast_demand": days,
        "first_date": days[0][0], "inventory_snapshot_id": "snapshot-1",
        "pilot_scope_version": "scope-1", "identity_bridge_version": "bridge-1",
        "forecast_run_id": "run-1", "forecast_origin_date": date(2026, 9, 27),
        "calculation_at": NOW,
    }
    with pytest.raises(ValueError, match="14日"):
        build_warehouse_projection(**{**arguments, "forecast_demand": days[:13]})
    with pytest.raises(ValueError, match="欠落"):
        build_warehouse_projection(
            **{**arguments, "forecast_demand": (*days[:7], days[8], *days[8:])}
        )
    with pytest.raises(ValueError, match="0以上"):
        build_warehouse_projection(
            **{**arguments, "forecast_demand": (*days[:1], (days[1][0], "-1"), *days[2:])}
        )
    with pytest.raises(ValueError, match="binary float"):
        build_warehouse_projection(**{**arguments, "starting_inventory_cases": 5.0})


def test_projection_cli_emits_shadow_and_versioned_days(tmp_path, capsys):
    _service, scope, bridge, _inventory, _snapshot_id = _ready(tmp_path)
    assert projection_main([
        "--sqlite", str(tmp_path / "pilot.sqlite3"),
        "--pilot-scope-version", scope.version.pilot_scope_version,
        "--identity-bridge-version", bridge.version.bridge_version,
        "--forecast-run-id", "run-pilot",
        "--calculation-at", (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "SHADOW"
    assert len(output["projections"]) == 10
    assert len(output["projections"][0]["days"]) == 14
    assert isinstance(output["projections"][0]["demand_7_days_cases"], str)


def test_legacy_completed_run_gets_conservative_availability_time(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE forecast_runs (run_id TEXT PRIMARY KEY, experiment_id TEXT,"
            "condition_fingerprint TEXT,provider_id TEXT,model_name TEXT,seed INTEGER,"
            "status TEXT,cancellation_requested INTEGER)"
        )
        db.execute(
            "INSERT INTO forecast_runs VALUES (?,?,?,?,?,?,?,?)",
            ("legacy", "experiment", "condition", "baseline", "model", 1, "SUCCEEDED", 0),
        )
    before = datetime.now(UTC)
    store = SqliteRunStore(path)
    assert store.get_run_finished_at("legacy") >= before - timedelta(seconds=1)
