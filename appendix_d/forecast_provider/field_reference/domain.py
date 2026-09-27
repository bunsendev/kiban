"""到着・工場供給を仮定しないShadow専用の参考補充量。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal

from ..expiry_simulation.domain import ExpirySimulation
from ..inventory_foundation.domain import canonical_datetime, canonical_decimal
from ..warehouse_projection.domain import HORIZON_DAYS, WarehouseProjection


def _quantity(value: Decimal | int | str, label: str, *, positive: bool = False) -> Decimal:
    result = Decimal(canonical_decimal(value))
    if result < 0 or (positive and result == 0):
        raise ValueError(f"{label}は{'0より大きい' if positive else '0以上'}CASEです")
    return result


@dataclass(frozen=True)
class FieldReferencePolicy:
    policy_version: str
    target_days: int
    safety_stock_cases: Decimal
    shipment_multiple_cases: Decimal
    expiry_policy_version: str
    confirmed_by: str
    reason: str
    confirmed_at: datetime


def build_reference_policy(
    *, target_days: int, safety_stock_cases: Decimal | int | str,
    shipment_multiple_cases: Decimal | int | str, expiry_policy_version: str,
    confirmed_by: str, reason: str, confirmed_at: datetime,
) -> FieldReferencePolicy:
    """業務確認した値だけで版を発行する。暗黙の既定値を持たない。"""

    if (
        isinstance(target_days, bool)
        or not isinstance(target_days, int)
        or not 1 <= target_days <= HORIZON_DAYS
    ):
        raise ValueError("target_daysは1〜14日の整数です")
    safety = _quantity(safety_stock_cases, "safety_stock_cases")
    multiple = _quantity(shipment_multiple_cases, "shipment_multiple_cases", positive=True)
    if not expiry_policy_version.strip() or not confirmed_by.strip() or not reason.strip():
        raise ValueError("期限policy版、確認者、理由は必須です")
    timestamp = canonical_datetime(confirmed_at, "confirmed_at")
    payload = {
        "format_version": "field-reference-policy-v1",
        "basis": "WAREHOUSE_NOW_NO_INBOUND_SHADOW",
        "target_days": target_days,
        "safety_stock_cases": canonical_decimal(safety),
        "shipment_multiple_cases": canonical_decimal(multiple),
        "expiry_policy_version": expiry_policy_version.strip(),
        "confirmed_by": confirmed_by.strip(),
        "reason": reason.strip(),
        "confirmed_at": timestamp,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return FieldReferencePolicy(
        f"field-reference-policy-{digest}", target_days, safety, multiple,
        expiry_policy_version.strip(), confirmed_by.strip(), reason.strip(),
        confirmed_at.astimezone(UTC),
    )


@dataclass(frozen=True)
class ReferenceQuantity:
    forecast_cases: Decimal
    unavailable_by_cutoff_cases: Decimal
    usable_opening_cases: Decimal
    safety_stock_cases: Decimal
    unrounded_gap_cases: Decimal
    reference_cases: Decimal


def calculate_reference_quantity(
    projection: WarehouseProjection, simulation: ExpirySimulation,
    policy: FieldReferencePolicy,
) -> ReferenceQuantity:
    """指定期間の需要＋安全在庫－期限内に使える現在庫を出荷単位へ切り上げる。"""

    if simulation.projection_id != projection.projection_id:
        raise ValueError("ProjectionとFEFOの計算元が一致しません")
    if simulation.policy_version != policy.expiry_policy_version:
        raise ValueError("FEFO policy版が参考数量policyと一致しません")
    if policy.confirmed_at > projection.calculation_at:
        raise ValueError("参考数量policyは計算時点に未確定です")
    if len(projection.days) < policy.target_days or len(simulation.days) < policy.target_days:
        raise ValueError("参考数量policyの対象期間に予測が不足しています")
    forecast = sum(
        (point.forecast_demand_cases for point in projection.days[:policy.target_days]),
        Decimal("0"),
    )
    unavailable = sum(
        (point.unconsumed_by_cutoff_cases for point in simulation.days[:policy.target_days]),
        Decimal("0"),
    )
    usable = max(Decimal("0"), projection.starting_inventory_cases - unavailable)
    gap = max(Decimal("0"), forecast + policy.safety_stock_cases - usable)
    rounded = (
        (gap / policy.shipment_multiple_cases).to_integral_value(rounding=ROUND_CEILING)
        * policy.shipment_multiple_cases
    )
    return ReferenceQuantity(
        forecast, unavailable, usable, policy.safety_stock_cases, gap, rounded,
    )
