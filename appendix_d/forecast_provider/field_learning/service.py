"""Pilot ScopeとidentityをGateにした現場検証台帳service。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from ..inventory_forecast_bridge import resolve_identity
from .contracts import FieldMode, OperatorDecision, OperatorReasonCode
from .domain import (
    build_actual_outcome_event,
    build_operator_decision_event,
    build_reference_case,
)


class FieldLearningService:
    def __init__(
        self,
        pilot_scope_store,
        identity_bridge_store,
        field_store,
        *,
        allowed_modes: frozenset[FieldMode] = frozenset({FieldMode.SHADOW}),
    ) -> None:
        self.pilot_scope_store = pilot_scope_store
        self.identity_bridge_store = identity_bridge_store
        self.field_store = field_store
        self.allowed_modes = allowed_modes

    def register_reference_case(
        self,
        *,
        business_date: date,
        jan: str,
        warehouse_id: str,
        forecast_run_id: str,
        inventory_snapshot_id: str,
        pilot_scope_version: str,
        identity_bridge_version: str,
        system_forecast_quantity: Decimal | int | str,
        system_reference_quantity: Decimal | int | str,
        policy_version: str,
        mode: FieldMode,
        known_at: datetime,
        recorded_at: datetime,
    ):
        if mode not in self.allowed_modes:
            raise PermissionError(f"{mode.value} modeは現場Gateで許可されていません")
        scope = self.pilot_scope_store.get(pilot_scope_version)
        if scope is None:
            raise KeyError(pilot_scope_version)
        if not scope.contains(jan, warehouse_id, business_date):
            raise ValueError("対象のJAN×WAREHOUSEは指定日のPilot Scope外です")
        bridge = self.identity_bridge_store.get(identity_bridge_version)
        if bridge is None:
            raise KeyError(identity_bridge_version)
        identity = resolve_identity(
            bridge,
            jan=jan,
            warehouse_id=warehouse_id,
            business_date=business_date,
            known_at=known_at,
        )
        value = build_reference_case(
            business_date=business_date,
            jan=identity.jan,
            canonical_product_id=identity.canonical_product_id,
            warehouse_id=identity.warehouse_id,
            forecast_center_id=identity.forecast_center_id,
            forecast_run_id=forecast_run_id,
            inventory_snapshot_id=inventory_snapshot_id,
            pilot_scope_version=pilot_scope_version,
            identity_bridge_version=identity.bridge_version,
            system_forecast_quantity=system_forecast_quantity,
            system_reference_quantity=system_reference_quantity,
            policy_version=policy_version,
            mode=mode,
            known_at=known_at,
            recorded_at=recorded_at,
        )
        return self.field_store.put_reference_case(value)

    def record_operator_decision(
        self,
        *,
        case_id: str,
        expected_revision: int,
        operator_decision: OperatorDecision,
        operator_quantity: Decimal | int | str | None,
        operator_reason_code: OperatorReasonCode | None,
        operator_comment: str | None,
        subject: str,
        known_at: datetime,
        recorded_at: datetime,
    ):
        case = self.field_store.get_reference_case(case_id)
        if case is None:
            raise KeyError(case_id)
        event = build_operator_decision_event(
            case=case,
            expected_revision=expected_revision,
            operator_decision=operator_decision,
            operator_quantity=operator_quantity,
            operator_reason_code=operator_reason_code,
            operator_comment=operator_comment,
            subject=subject,
            known_at=known_at,
            recorded_at=recorded_at,
        )
        return self.field_store.append_operator_decision(event, expected_revision)

    def record_actual_outcome(self, *, case_id: str, expected_revision: int, **values):
        if self.field_store.get_reference_case(case_id) is None:
            raise KeyError(case_id)
        event = build_actual_outcome_event(
            case_id=case_id,
            expected_revision=expected_revision,
            **values,
        )
        return self.field_store.append_actual_outcome(event, expected_revision)
