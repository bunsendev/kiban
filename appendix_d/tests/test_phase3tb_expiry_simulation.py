"""Phase 3T-B: FEFO消化、期限内未消化、時点条件とCLIの契約。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from forecast_provider.expiry_simulation import (
    ExpirySimulationBlocked,
    ExpirySimulationService,
    build_expiry_policy,
    simulate_expiry,
)
from forecast_provider.expiry_simulation.cli import main as expiry_main
from forecast_provider.warehouse_projection import build_warehouse_projection
from tests.test_phase3ta1_pilot_intake import NOW, _jan
from tests.test_phase3ta2_warehouse_projection import _ready


def _projection(*, opening="8", daily="2"):
    start = date(2026, 9, 28)
    return build_warehouse_projection(
        jan=_jan(0), warehouse_id="warehouse-east", starting_inventory_cases=opening,
        forecast_demand=tuple((start + timedelta(days=i), daily) for i in range(14)),
        first_date=start, inventory_snapshot_id="snapshot", pilot_scope_version="scope",
        identity_bridge_version="bridge", forecast_run_id="run",
        forecast_origin_date=start - timedelta(days=1), calculation_at=NOW,
    )


def _policy(*, minimum=0, attention=2, confirmed_at=NOW):
    return build_expiry_policy(
        minimum_remaining_days=minimum, attention_days=attention,
        confirmed_by="reviewer", reason="Shadow計算条件確認", confirmed_at=confirmed_at,
    )


def test_fefo_consumes_nearest_expiry_first_and_reconciles():
    projection = _projection()
    buckets = ((date(2026, 10, 1), "5"), (date(2026, 9, 28), "3"))
    result = simulate_expiry(projection, buckets, _policy())
    assert result == simulate_expiry(projection, tuple(reversed(buckets)), _policy())
    assert result.buckets[0].consumed_cases == Decimal("2")
    assert result.buckets[0].unconsumed_by_cutoff_cases == Decimal("1")
    assert result.buckets[1].consumed_cases == Decimal("5")
    assert result.unconsumed_by_cutoff_cases == Decimal("1")
    assert result.consumed_cases == Decimal("7")
    assert result.unmet_demand_cases == Decimal("21")
    assert result.days[0].unconsumed_by_cutoff_cases == Decimal("1")
    assert result.days[0].attention_cases == Decimal("0")
    assert result.days[1].attention_cases == Decimal("3")
    assert result.days[3].unconsumed_by_cutoff_cases == Decimal("0")


def test_minimum_remaining_days_changes_cutoff_without_changing_original_expiry():
    result = simulate_expiry(
        _projection(opening="3", daily="1"),
        ((date(2026, 9, 29), "3"),), _policy(minimum=1),
    )
    assert result.buckets[0].expiry_date == date(2026, 9, 29)
    assert result.buckets[0].last_usable_date == date(2026, 9, 28)
    assert result.buckets[0].consumed_cases == Decimal("1")
    assert result.buckets[0].unconsumed_by_cutoff_cases == Decimal("2")


def test_duplicate_same_expiry_buckets_have_same_identity_as_aggregated_bucket():
    projection = _projection(opening="8")
    expiry = date(2026, 12, 1)
    split = simulate_expiry(projection, ((expiry, "3"), (expiry, "5")), _policy())
    aggregated = simulate_expiry(projection, ((expiry, "8"),), _policy())
    assert split == aggregated
    assert split.buckets[0].remaining_after_horizon_cases == Decimal("0")


def test_unknown_expiry_float_mismatch_and_future_policy_fail_closed():
    projection = _projection()
    with pytest.raises(ValueError, match="賞味期限不明"):
        simulate_expiry(projection, ((None, "8"),), _policy())
    with pytest.raises(ValueError, match="binary float"):
        simulate_expiry(projection, ((date(2026, 12, 1), 8.0),), _policy())
    with pytest.raises(ValueError, match="一致しません"):
        simulate_expiry(projection, ((date(2026, 12, 1), "7"),), _policy())
    with pytest.raises(ValueError, match="未確定"):
        simulate_expiry(
            projection, ((date(2026, 12, 1), "8"),),
            _policy(confirmed_at=NOW + timedelta(seconds=1)),
        )
    with pytest.raises(ValueError, match="0以上"):
        _policy(minimum=-1)


def test_service_uses_approved_snapshot_and_point_forecast(tmp_path):
    projection_service, scope, bridge, _inventory, snapshot_id = _ready(tmp_path)
    result = ExpirySimulationService(projection_service).calculate(
        calculation_at=datetime.now(UTC) + timedelta(minutes=1),
        pilot_scope_version=scope.version.pilot_scope_version,
        identity_bridge_version=bridge.version.bridge_version,
        forecast_run_id="run-pilot", policy=_policy(),
    )
    assert result.inventory_snapshot_id == snapshot_id
    assert result.snapshot_at <= result.calculation_at
    assert result.forecast_finished_at <= result.calculation_at
    assert len(result.simulations) == 10
    item = next(value for value in result.simulations if value.jan == _jan(0))
    assert item.opening_cases == Decimal("5")
    assert item.consumed_cases == Decimal("5")
    assert item.unmet_demand_cases == Decimal("9")
    assert item.unconsumed_by_cutoff_cases == Decimal("0")
    with pytest.raises(ExpirySimulationBlocked, match="EXPIRY_POLICY_NOT_KNOWN_AS_OF"):
        ExpirySimulationService(projection_service).calculate(
            calculation_at=datetime.now(UTC) + timedelta(minutes=1),
            pilot_scope_version=scope.version.pilot_scope_version,
            identity_bridge_version=bridge.version.bridge_version,
            forecast_run_id="run-pilot",
            policy=_policy(confirmed_at=datetime.now(UTC) + timedelta(days=1)),
        )


def test_cli_emits_shadow_with_policy_and_bucket_results(tmp_path, capsys):
    _service, scope, bridge, _inventory, _snapshot_id = _ready(tmp_path)
    assert expiry_main([
        "--sqlite", str(tmp_path / "pilot.sqlite3"),
        "--pilot-scope-version", scope.version.pilot_scope_version,
        "--identity-bridge-version", bridge.version.bridge_version,
        "--forecast-run-id", "run-pilot",
        "--calculation-at", (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        "--minimum-remaining-days", "0", "--attention-days", "7",
        "--policy-confirmed-by", "reviewer", "--policy-reason", "Shadow計算条件確認",
        "--policy-confirmed-at", NOW.isoformat(),
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "SHADOW"
    assert output["policy"]["minimum_remaining_days"] == 0
    assert len(output["simulations"][0]["days"]) == 14
    assert output["simulations"][0]["buckets"][0]["expiry_date"]
