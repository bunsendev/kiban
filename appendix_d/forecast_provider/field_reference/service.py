"""承認済みPilotの計算結果からShadow reference caseを一括生成する。"""

from __future__ import annotations

from datetime import datetime

from ..field_learning.contracts import FieldMode
from ..field_learning.domain import build_reference_case
from ..inventory_forecast_bridge import resolve_identity
from ..inventory_foundation.domain import canonical_datetime
from .domain import FieldReferencePolicy, build_reference_policy, calculate_reference_quantity


class FieldReferenceBatchService:
    def __init__(self, expiry_service, pilot_store, bridge_store, field_store):
        self.expiry_service = expiry_service
        self.pilot_store = pilot_store
        self.bridge_store = bridge_store
        self.field_store = field_store

    def prepare(
        self, *, calculation_at: datetime, pilot_scope_version: str,
        identity_bridge_version: str, forecast_run_id: str,
        expiry_policy, reference_policy: FieldReferencePolicy,
        recorded_at: datetime,
    ):
        canonical_datetime(recorded_at, "recorded_at")
        if reference_policy != build_reference_policy(
            target_days=reference_policy.target_days,
            safety_stock_cases=reference_policy.safety_stock_cases,
            shipment_multiple_cases=reference_policy.shipment_multiple_cases,
            expiry_policy_version=reference_policy.expiry_policy_version,
            confirmed_by=reference_policy.confirmed_by,
            reason=reference_policy.reason,
            confirmed_at=reference_policy.confirmed_at,
        ):
            raise ValueError("参考数量policy版の内容が一致しません")
        if reference_policy.expiry_policy_version != expiry_policy.policy_version:
            raise ValueError("参考数量policyと期限policyの版が一致しません")
        if reference_policy.confirmed_at > calculation_at:
            raise ValueError("参考数量policyは計算時点に未確定です")
        batch = self.expiry_service.calculate(
            calculation_at=calculation_at,
            pilot_scope_version=pilot_scope_version,
            identity_bridge_version=identity_bridge_version,
            forecast_run_id=forecast_run_id,
            policy=expiry_policy,
        )
        if recorded_at < batch.calculation_at:
            raise ValueError("recorded_atは計算時点以降です")
        scope = self.pilot_store.get(pilot_scope_version)
        bridge = self.bridge_store.get(identity_bridge_version)
        if scope is None or bridge is None:
            raise ValueError("Pilot scopeまたはidentity bridgeがありません")
        simulations = {(item.jan, item.warehouse_id): item for item in batch.simulations}
        cases = []
        for projection in batch.warehouse_projections:
            business_date = projection.forecast_origin_date
            if not scope.contains(projection.jan, projection.warehouse_id, business_date):
                raise ValueError("Pilot scope外の参考caseです")
            identity = resolve_identity(
                bridge, jan=projection.jan, warehouse_id=projection.warehouse_id,
                business_date=business_date, known_at=batch.calculation_at,
            )
            quantity = calculate_reference_quantity(
                projection, simulations[(projection.jan, projection.warehouse_id)],
                reference_policy,
            )
            cases.append(build_reference_case(
                business_date=business_date,
                jan=identity.jan,
                canonical_product_id=identity.canonical_product_id,
                warehouse_id=identity.warehouse_id,
                forecast_center_id=identity.forecast_center_id,
                forecast_run_id=forecast_run_id,
                inventory_snapshot_id=batch.inventory_snapshot_id,
                pilot_scope_version=pilot_scope_version,
                identity_bridge_version=identity.bridge_version,
                system_forecast_quantity=quantity.forecast_cases,
                system_reference_quantity=quantity.reference_cases,
                policy_version=reference_policy.policy_version,
                mode=FieldMode.SHADOW,
                known_at=batch.calculation_at,
                recorded_at=recorded_at,
            ))
        if not cases:
            raise ValueError("参考caseの対象がありません")
        return tuple(cases)

    def register(self, **values):
        """検証済みの全件をpolicyと一緒に原子的に保存する。"""

        cases = self.prepare(**values)
        return self.field_store.put_reference_batch(values["reference_policy"], cases)
