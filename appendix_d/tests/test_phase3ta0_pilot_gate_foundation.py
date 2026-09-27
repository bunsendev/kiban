"""Phase 3T-A-0: Pilot Scope、identity bridge、Feedback Ledger。"""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from forecast_provider.field_learning import (
    FieldLearningConflict,
    FieldLearningService,
    FieldMode,
    OperatorDecision,
    OperatorReasonCode,
    PostgresFieldLearningStore,
    SqliteFieldLearningStore,
)
from forecast_provider.inventory_forecast_bridge import (
    IdentityResolutionError,
    PostgresInventoryForecastBridgeStore,
    SqliteInventoryForecastBridgeStore,
    build_inventory_forecast_bridge,
    resolve_identity,
)
from forecast_provider.inventory_foundation import (
    InventoryExpiryBucket,
    SourceKind,
    build_inventory_snapshot,
)
from forecast_provider.pilot_scope import (
    PostgresPilotScopeStore,
    SqlitePilotScopeStore,
    build_pilot_scope,
    build_scope_reconciliation,
    build_scoped_snapshot_reference,
)

NOW = datetime(2026, 9, 27, 1, 2, 3, tzinfo=UTC)
BUSINESS_DATE = date(2026, 9, 27)


def _jan(index: int) -> str:
    body = f"49012345{index:04d}"
    weighted = sum(
        int(digit) * (3 if offset % 2 == 0 else 1) for offset, digit in enumerate(reversed(body))
    )
    return body + str((10 - weighted % 10) % 10)


def _scope():
    return build_pilot_scope(
        pairs=[(_jan(index), "warehouse-east") for index in range(10)],
        effective_from=BUSINESS_DATE,
        effective_to=BUSINESS_DATE + timedelta(days=30),
        approved_by="pilot-owner",
        reason="代表10商品でShadow検証",
        created_at=NOW,
    )


def _bridge(*, ambiguous: bool = False):
    records = [
        (
            _jan(0),
            "warehouse-east",
            "canonical-0000",
            "forecast-center-east",
            BUSINESS_DATE,
            None,
        )
    ]
    if ambiguous:
        records.append(
            (
                _jan(0),
                "warehouse-east",
                "canonical-conflict",
                "forecast-center-east",
                BUSINESS_DATE,
                None,
            )
        )
    return build_inventory_forecast_bridge(
        records=records,
        created_by="master-owner",
        reason="正式商品・倉庫対応",
        created_at=NOW,
    )


def _service(tmp_path):
    database = tmp_path / "pilot.sqlite3"
    scopes = SqlitePilotScopeStore(database)
    bridges = SqliteInventoryForecastBridgeStore(database)
    fields = SqliteFieldLearningStore(database)
    scope = scopes.put(_scope())
    bridge = bridges.put(_bridge())
    return FieldLearningService(scopes, bridges, fields), fields, scope, bridge


def _reference(service, scope, bridge, **overrides):
    values = {
        "business_date": BUSINESS_DATE,
        "jan": _jan(0),
        "warehouse_id": "warehouse-east",
        "forecast_run_id": "forecast-run-1",
        "inventory_snapshot_id": "inventory-snapshot-1",
        "pilot_scope_version": scope.version.pilot_scope_version,
        "identity_bridge_version": bridge.version.bridge_version,
        "system_forecast_quantity": "125.5",
        "system_reference_quantity": "20",
        "policy_version": "shadow-policy-v1",
        "mode": FieldMode.SHADOW,
        "known_at": NOW,
        "recorded_at": NOW + timedelta(minutes=1),
    }
    values.update(overrides)
    return service.register_reference_case(**values)


def test_pilot_scope_is_deterministic_and_requires_10_to_20_products() -> None:
    scope = _scope()
    reversed_scope = build_pilot_scope(
        pairs=list(reversed([(item.jan, item.warehouse_id) for item in scope.items])),
        effective_from=BUSINESS_DATE,
        effective_to=BUSINESS_DATE + timedelta(days=30),
        approved_by="pilot-owner",
        reason="代表10商品でShadow検証",
        created_at=NOW + timedelta(hours=1),
    )

    assert scope.version.pilot_scope_version == reversed_scope.version.pilot_scope_version
    assert scope.contains(_jan(0), "warehouse-east", BUSINESS_DATE)
    assert not scope.contains(_jan(0), "warehouse-west", BUSINESS_DATE)
    with pytest.raises(ValueError, match="10〜20"):
        build_pilot_scope(
            pairs=[(_jan(index), "warehouse-east") for index in range(9)],
            effective_from=BUSINESS_DATE,
            effective_to=None,
            approved_by="owner",
            reason="少なすぎる",
            created_at=NOW,
        )


def test_content_addressed_scope_registration_is_concurrently_idempotent(tmp_path) -> None:
    store = SqlitePilotScopeStore(tmp_path / "scope.sqlite3")
    scope = _scope()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: store.put(scope), range(2)))

    assert results == [scope, scope]


def test_scope_reconciliation_keeps_out_of_scope_separate() -> None:
    result = build_scope_reconciliation(
        source_sha256="a" * 64,
        source_row_count=100,
        scoped_row_count=20,
        out_of_scope_row_count=80,
        quarantined_scope_row_count=0,
        source_quantity_cases="1000",
        scoped_quantity_cases="200",
        out_of_scope_quantity_cases="800",
        quarantined_scope_quantity_cases="0",
    )

    assert result.approval_ready is True
    assert result.out_of_scope_row_count == 80
    with pytest.raises(ValueError, match="原本数量"):
        build_scope_reconciliation(
            source_sha256="a" * 64,
            source_row_count=100,
            scoped_row_count=20,
            out_of_scope_row_count=80,
            quarantined_scope_row_count=0,
            source_quantity_cases="999",
            scoped_quantity_cases="200",
            out_of_scope_quantity_cases="800",
            quarantined_scope_quantity_cases="0",
        )


def test_scoped_snapshot_reference_prevents_partial_data_from_looking_complete(tmp_path) -> None:
    scope = _scope()
    reconciliation = build_scope_reconciliation(
        source_sha256="a" * 64,
        source_row_count=100,
        scoped_row_count=20,
        out_of_scope_row_count=80,
        quarantined_scope_row_count=0,
        source_quantity_cases="1000",
        scoped_quantity_cases="200",
        out_of_scope_quantity_cases="800",
        quarantined_scope_quantity_cases="0",
    )
    snapshot = build_inventory_snapshot(
        snapshot_at=NOW,
        known_at=NOW,
        source_kind=SourceKind.CSV,
        source_reference="source-a",
        source_sha256="a" * 64,
        mapping_version="mapping-v1",
        location_master_version="location-v1",
        product_mapping_version="product-v1",
        buckets=[
            InventoryExpiryBucket(
                _jan(0),
                "canonical-0000",
                "warehouse-east",
                BUSINESS_DATE + timedelta(days=60),
                Decimal("200"),
            )
        ],
        created_at=NOW,
    )
    reference = build_scoped_snapshot_reference(
        inventory_snapshot=snapshot,
        pilot_scope=scope,
        reconciliation=reconciliation,
        recorded_at=NOW + timedelta(minutes=1),
    )
    store = SqlitePilotScopeStore(tmp_path / "scope.sqlite3")
    store.put(scope)

    store.put_scoped_snapshot(reference)

    assert store.get_scoped_snapshot(reference.scoped_snapshot_id) == reference
    assert reference.scope_kind.value == "PILOT_PARTIAL"
    assert reference.reconciliation.out_of_scope_row_count == 80


def test_identity_resolution_uses_effective_date_and_known_at() -> None:
    bridge = _bridge()
    resolved = resolve_identity(
        bridge,
        jan=_jan(0),
        warehouse_id="warehouse-east",
        business_date=BUSINESS_DATE,
        known_at=NOW,
    )
    assert resolved.canonical_product_id == "canonical-0000"
    assert resolved.forecast_center_id == "forecast-center-east"

    with pytest.raises(IdentityResolutionError) as not_known:
        resolve_identity(
            bridge,
            jan=_jan(0),
            warehouse_id="warehouse-east",
            business_date=BUSINESS_DATE,
            known_at=NOW - timedelta(seconds=1),
        )
    assert not_known.value.code == "BRIDGE_NOT_KNOWN_AS_OF"
    with pytest.raises(IdentityResolutionError) as ambiguous:
        resolve_identity(
            _bridge(ambiguous=True),
            jan=_jan(0),
            warehouse_id="warehouse-east",
            business_date=BUSINESS_DATE,
            known_at=NOW,
        )
    assert ambiguous.value.code == "IDENTITY_AMBIGUOUS"


def test_shadow_reference_is_gated_by_scope_identity_and_mode(tmp_path) -> None:
    service, store, scope, bridge = _service(tmp_path)
    case = _reference(service, scope, bridge)

    assert case.canonical_product_id == "canonical-0000"
    assert case.forecast_center_id == "forecast-center-east"
    assert store.get_reference_case(case.case_id) == case
    assert _reference(service, scope, bridge) == case
    with pytest.raises(ValueError, match="Scope外"):
        _reference(service, scope, bridge, jan=_jan(9), warehouse_id="warehouse-west")
    with pytest.raises(PermissionError, match="ADVISORY"):
        _reference(service, scope, bridge, mode=FieldMode.ADVISORY)


def test_operator_decisions_are_validated_and_append_only(tmp_path) -> None:
    service, store, scope, bridge = _service(tmp_path)
    case = _reference(service, scope, bridge)
    first = service.record_operator_decision(
        case_id=case.case_id,
        expected_revision=0,
        operator_decision=OperatorDecision.OBSERVED,
        operator_quantity="18",
        operator_reason_code=None,
        operator_comment=None,
        subject="operator-1",
        known_at=NOW + timedelta(minutes=2),
        recorded_at=NOW + timedelta(minutes=3),
    )
    second = service.record_operator_decision(
        case_id=case.case_id,
        expected_revision=1,
        operator_decision=OperatorDecision.INCREASED,
        operator_quantity="25",
        operator_reason_code=OperatorReasonCode.EXPECTED_LARGE_ORDER,
        operator_comment="得意先情報を確認",
        subject="operator-1",
        known_at=NOW + timedelta(minutes=4),
        recorded_at=NOW + timedelta(minutes=5),
    )

    assert (first.revision, second.revision) == (1, 2)
    assert [event.revision for event in store.list_operator_decisions(case.case_id)] == [1, 2]
    with pytest.raises(FieldLearningConflict, match="先に"):
        service.record_operator_decision(
            case_id=case.case_id,
            expected_revision=1,
            operator_decision=OperatorDecision.ACCEPTED,
            operator_quantity="20",
            operator_reason_code=None,
            operator_comment=None,
            subject="stale-operator",
            known_at=NOW + timedelta(minutes=6),
            recorded_at=NOW + timedelta(minutes=7),
        )
    with pytest.raises(ValueError, match="reason code"):
        service.record_operator_decision(
            case_id=case.case_id,
            expected_revision=2,
            operator_decision=OperatorDecision.DECREASED,
            operator_quantity="15",
            operator_reason_code=None,
            operator_comment=None,
            subject="operator-1",
            known_at=NOW + timedelta(minutes=6),
            recorded_at=NOW + timedelta(minutes=7),
        )


def test_actual_events_preserve_missing_and_confirmed_zero(tmp_path) -> None:
    service, store, scope, bridge = _service(tmp_path)
    case = _reference(service, scope, bridge)
    first = service.record_actual_outcome(
        case_id=case.case_id,
        expected_revision=0,
        source_version="shipment-actual-v1",
        source_sha256="b" * 64,
        actual_shipped_quantity="20",
        actual_demand_quantity=None,
        stockout_quantity="0",
        expired_quantity=None,
        interwarehouse_transfer_quantity=None,
        known_at=NOW + timedelta(days=1),
        recorded_at=NOW + timedelta(days=1, minutes=1),
    )
    second = service.record_actual_outcome(
        case_id=case.case_id,
        expected_revision=1,
        source_version="shipment-actual-v2",
        source_sha256="c" * 64,
        actual_shipped_quantity="21",
        actual_demand_quantity="22",
        stockout_quantity="0",
        expired_quantity="0",
        interwarehouse_transfer_quantity="0",
        known_at=NOW + timedelta(days=2),
        recorded_at=NOW + timedelta(days=2, minutes=1),
    )

    assert first.actual_demand_quantity is None
    assert first.stockout_quantity == Decimal("0")
    assert second.revision == 2
    assert store.list_actual_outcomes(case.case_id) == [first, second]


def test_other_reason_requires_short_comment(tmp_path) -> None:
    service, _store, scope, bridge = _service(tmp_path)
    case = _reference(service, scope, bridge)
    with pytest.raises(ValueError, match="OTHER"):
        service.record_operator_decision(
            case_id=case.case_id,
            expected_revision=0,
            operator_decision=OperatorDecision.REJECTED,
            operator_quantity=None,
            operator_reason_code=OperatorReasonCode.OTHER,
            operator_comment=None,
            subject="operator-1",
            known_at=NOW,
            recorded_at=NOW,
        )


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_stores_follow_the_same_gate_contract() -> None:
    suffix = uuid.uuid4().hex
    dsn = os.environ["KIBAN_TEST_POSTGRES_DSN"]
    scopes = PostgresPilotScopeStore(dsn)
    bridges = PostgresInventoryForecastBridgeStore(dsn)
    fields = PostgresFieldLearningStore(dsn)
    scope = scopes.put(
        build_pilot_scope(
            pairs=[(_jan(index), f"warehouse-{suffix}") for index in range(10)],
            effective_from=BUSINESS_DATE,
            effective_to=None,
            approved_by="postgres-test",
            reason=f"fixture-{suffix}",
            created_at=NOW,
        )
    )
    bridge = bridges.put(
        build_inventory_forecast_bridge(
            records=[
                (
                    _jan(0),
                    f"warehouse-{suffix}",
                    f"canonical-{suffix}",
                    f"center-{suffix}",
                    BUSINESS_DATE,
                    None,
                )
            ],
            created_by="postgres-test",
            reason=f"fixture-{suffix}",
            created_at=NOW,
        )
    )
    service = FieldLearningService(scopes, bridges, fields)

    case = service.register_reference_case(
        business_date=BUSINESS_DATE,
        jan=_jan(0),
        warehouse_id=f"warehouse-{suffix}",
        forecast_run_id=f"forecast-{suffix}",
        inventory_snapshot_id=f"inventory-{suffix}",
        pilot_scope_version=scope.version.pilot_scope_version,
        identity_bridge_version=bridge.version.bridge_version,
        system_forecast_quantity="10",
        system_reference_quantity="2",
        policy_version="shadow-policy-v1",
        mode=FieldMode.SHADOW,
        known_at=NOW,
        recorded_at=NOW,
    )
    event = service.record_operator_decision(
        case_id=case.case_id,
        expected_revision=0,
        operator_decision=OperatorDecision.NO_ACTION,
        operator_quantity="0",
        operator_reason_code=None,
        operator_comment=None,
        subject="postgres-test",
        known_at=NOW,
        recorded_at=NOW,
    )

    assert scopes.get(scope.version.pilot_scope_version) == scope
    assert bridges.get(bridge.version.bridge_version) == bridge
    assert fields.get_reference_case(case.case_id) == case
    assert fields.list_operator_decisions(case.case_id) == [event]
