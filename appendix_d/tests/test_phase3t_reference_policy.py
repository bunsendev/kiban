"""未承認値を補完せず、Shadow参考数量とcaseを同一入力から再現する。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from forecast_provider.expiry_simulation import (
    ExpirySimulationService,
    build_expiry_policy,
    simulate_expiry,
)
from forecast_provider.field_learning import SqliteFieldLearningStore
from forecast_provider.field_reference import (
    FieldReferenceBatchService,
    build_reference_policy,
    calculate_reference_quantity,
)
from forecast_provider.field_reference.cli import main as reference_main
from forecast_provider.warehouse_projection import build_warehouse_projection
from tests.test_phase3ta1_pilot_intake import NOW, _jan
from tests.test_phase3ta2_warehouse_projection import _ready


def _prepared(tmp_path):
    projection_service, scope, bridge, _inventory, _snapshot_id = _ready(tmp_path)
    expiry_service = ExpirySimulationService(projection_service)
    store = SqliteFieldLearningStore(tmp_path / "pilot.sqlite3")
    service = FieldReferenceBatchService(
        expiry_service, projection_service.pilot_store,
        projection_service.bridge_store, store,
    )
    expiry = build_expiry_policy(
        minimum_remaining_days=0, attention_days=7,
        confirmed_by="reviewer", reason="人工データ用", confirmed_at=NOW,
    )
    policy = build_reference_policy(
        target_days=7, safety_stock_cases="2", shipment_multiple_cases="3",
        expiry_policy_version=expiry.policy_version,
        confirmed_by="reviewer", reason="人工Pilot向けShadow条件", confirmed_at=NOW,
    )
    args = {
        "calculation_at": datetime.now(UTC),
        "pilot_scope_version": scope.version.pilot_scope_version,
        "identity_bridge_version": bridge.version.bridge_version,
        "forecast_run_id": "run-pilot",
        "expiry_policy": expiry,
        "reference_policy": policy,
        "recorded_at": datetime.now(UTC) + timedelta(minutes=2),
    }
    return service, store, args


def test_reference_policy_requires_explicit_confirmed_values():
    with pytest.raises(TypeError):
        build_reference_policy()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="target_days"):
        build_reference_policy(
            target_days=0, safety_stock_cases="0", shipment_multiple_cases="1",
            expiry_policy_version="expiry-v1", confirmed_by="reviewer",
            reason="確認", confirmed_at=NOW,
        )
    with pytest.raises(ValueError, match="0より大きい"):
        build_reference_policy(
            target_days=7, safety_stock_cases="0", shipment_multiple_cases="0",
            expiry_policy_version="expiry-v1", confirmed_by="reviewer",
            reason="確認", confirmed_at=NOW,
        )


def test_reference_batch_is_deterministic_and_dry_run_does_not_write(tmp_path):
    service, store, args = _prepared(tmp_path)
    first = service.prepare(**args)
    assert first == service.prepare(**args)
    assert len(first) == 10
    assert store.list_reference_cases() == []
    first_case = next(case for case in first if case.system_reference_quantity == Decimal("6"))
    assert first_case.system_forecast_quantity == Decimal("7")
    saved = service.register(**args)
    assert saved == first
    assert service.register(**args) == first
    later = service.register(**{**args, "recorded_at": args["recorded_at"] + timedelta(minutes=5)})
    assert later == first
    assert len(store.list_reference_cases()) == 10
    assert store.get_reference_case(first_case.case_id) == first_case
    assert store.get_reference_policy(args["reference_policy"].policy_version) == args[
        "reference_policy"
    ]


def test_policy_mismatch_or_future_confirmation_cannot_create_cases(tmp_path):
    service, store, args = _prepared(tmp_path)
    with pytest.raises(ValueError, match="内容が一致"):
        service.register(**{
            **args,
            "reference_policy": replace(args["reference_policy"], expiry_policy_version="other"),
        })
    with pytest.raises(ValueError, match="未確定"):
        service.register(**{
            **args,
            "reference_policy": build_reference_policy(
                target_days=7, safety_stock_cases="2", shipment_multiple_cases="3",
                expiry_policy_version=args["expiry_policy"].policy_version,
                confirmed_by="reviewer", reason="未来の確認",
                confirmed_at=args["calculation_at"] + timedelta(minutes=1),
            ),
        })
    assert store.list_reference_cases() == []


def test_invalid_case_rolls_back_policy_and_all_cases(tmp_path):
    service, store, args = _prepared(tmp_path)
    cases = service.prepare(**args)
    conflicting = replace(cases[-1], content_sha256="f" * 64)
    store.put_reference_case(conflicting)
    with pytest.raises(ValueError, match="内容が一致"):
        store.put_reference_batch(args["reference_policy"], cases)
    assert store.get_reference_policy(args["reference_policy"].policy_version) is None
    assert store.list_reference_cases() == [conflicting]


def test_expiry_loss_is_counted_and_shipment_multiple_is_rounded(tmp_path):
    _service, _store, args = _prepared(tmp_path)
    projection = build_warehouse_projection(
        jan=_jan(0), warehouse_id="warehouse-east",
        starting_inventory_cases="5",
        forecast_demand=tuple(
            (date(2026, 9, 28) + timedelta(days=index), "1")
            for index in range(14)
        ),
        first_date=date(2026, 9, 28), inventory_snapshot_id="snapshot-1",
        pilot_scope_version="scope-1", identity_bridge_version="bridge-1",
        forecast_run_id="run-1", forecast_origin_date=date(2026, 9, 27),
        calculation_at=args["calculation_at"],
    )
    simulation = simulate_expiry(
        projection, ((date(2026, 9, 29), "5"),), args["expiry_policy"]
    )
    result = calculate_reference_quantity(projection, simulation, args["reference_policy"])
    assert result.unavailable_by_cutoff_cases == Decimal("3")
    assert result.usable_opening_cases == Decimal("2")
    assert result.unrounded_gap_cases == Decimal("7")
    assert result.reference_cases == Decimal("9")
    with pytest.raises(ValueError, match="FEFO policy版"):
        calculate_reference_quantity(
            projection, simulation,
            replace(args["reference_policy"], expiry_policy_version="wrong"),
        )


def test_cli_dry_run_then_explicit_apply(tmp_path, capsys):
    service, store, args = _prepared(tmp_path)
    del service
    policy = args["reference_policy"]
    expiry = args["expiry_policy"]
    command = [
        "--sqlite", str(tmp_path / "pilot.sqlite3"),
        "--pilot-scope-version", args["pilot_scope_version"],
        "--identity-bridge-version", args["identity_bridge_version"],
        "--forecast-run-id", args["forecast_run_id"],
        "--calculation-at", args["calculation_at"].isoformat(),
        "--minimum-remaining-days", str(expiry.minimum_remaining_days),
        "--attention-days", str(expiry.attention_days),
        "--expiry-policy-confirmed-by", expiry.confirmed_by,
        "--expiry-policy-reason", expiry.reason,
        "--expiry-policy-confirmed-at", expiry.confirmed_at.isoformat(),
        "--target-days", str(policy.target_days),
        "--safety-stock-cases", str(policy.safety_stock_cases),
        "--shipment-multiple-cases", str(policy.shipment_multiple_cases),
        "--reference-policy-confirmed-by", policy.confirmed_by,
        "--reference-policy-reason", policy.reason,
        "--reference-policy-confirmed-at", policy.confirmed_at.isoformat(),
    ]
    assert reference_main(command) == 0
    assert '"status": "DRY_RUN"' in capsys.readouterr().out
    assert store.list_reference_cases() == []
    assert reference_main([*command, "--apply"]) == 0
    assert '"status": "APPLIED"' in capsys.readouterr().out
    assert len(store.list_reference_cases()) == 10
