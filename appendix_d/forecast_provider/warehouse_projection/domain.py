"""Phase 3T-A: 補充・期限消化を仮定しない倉庫の日別gross在庫推移。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from ..inventory_foundation.domain import canonical_datetime, canonical_decimal, validate_jan

HORIZON_DAYS = 14


def _quantity(value: Decimal | int | str, label: str) -> Decimal:
    result = Decimal(canonical_decimal(value))
    if result < 0:
        raise ValueError(f"{label}は0以上です")
    return result


@dataclass(frozen=True)
class WarehouseProjectionDay:
    business_date: date
    forecast_demand_cases: Decimal
    gross_remaining_cases: Decimal
    cumulative_shortfall_cases: Decimal


@dataclass(frozen=True)
class WarehouseProjection:
    projection_id: str
    content_sha256: str
    jan: str
    warehouse_id: str
    starting_inventory_cases: Decimal
    demand_7_days_cases: Decimal
    demand_14_days_cases: Decimal
    first_shortage_date: date | None
    days: tuple[WarehouseProjectionDay, ...]
    inventory_snapshot_id: str
    pilot_scope_version: str
    identity_bridge_version: str
    forecast_run_id: str
    forecast_origin_date: date
    calculation_at: datetime


def build_warehouse_projection(
    *,
    jan: str,
    warehouse_id: str,
    starting_inventory_cases: Decimal | int | str,
    forecast_demand: tuple[tuple[date, Decimal | int | str], ...],
    first_date: date,
    inventory_snapshot_id: str,
    pilot_scope_version: str,
    identity_bridge_version: str,
    forecast_run_id: str,
    forecast_origin_date: date,
    calculation_at: datetime,
) -> WarehouseProjection:
    """翌日から14日、入庫なしのgross残高と累積不足を決定的に算出する。"""

    jan = validate_jan(jan)
    required = (warehouse_id, inventory_snapshot_id, pilot_scope_version,
                identity_bridge_version, forecast_run_id)
    if any(not value or not value.strip() for value in required):
        raise ValueError("Projectionのidentity/versionは必須です")
    if len(forecast_demand) != HORIZON_DAYS:
        raise ValueError("需要予測は翌日から連続14日分が必要です")
    canonical_datetime(calculation_at, "calculation_at")
    opening = _quantity(starting_inventory_cases, "starting_inventory_cases")
    balance = opening
    cumulative = Decimal("0")
    days = []
    first_shortage = None
    for index, (business_date, raw_demand) in enumerate(forecast_demand):
        expected = first_date + timedelta(days=index)
        if business_date != expected:
            raise ValueError("需要予測の日付に欠落・重複・順序違いがあります")
        demand = _quantity(raw_demand, "forecast_demand_cases")
        cumulative += demand
        balance = opening - cumulative
        shortfall = max(Decimal("0"), -balance)
        if first_shortage is None and shortfall > 0:
            first_shortage = business_date
        days.append(WarehouseProjectionDay(business_date, demand, balance, shortfall))
    payload = {
        "format_version": "warehouse-projection-v1",
        "jan": jan,
        "warehouse_id": warehouse_id.strip(),
        "starting_inventory_cases": canonical_decimal(opening),
        "days": [
            (day.business_date.isoformat(), canonical_decimal(day.forecast_demand_cases))
            for day in days
        ],
        "inventory_snapshot_id": inventory_snapshot_id,
        "pilot_scope_version": pilot_scope_version,
        "identity_bridge_version": identity_bridge_version,
        "forecast_run_id": forecast_run_id,
        "forecast_origin_date": forecast_origin_date.isoformat(),
        "calculation_at": canonical_datetime(calculation_at),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return WarehouseProjection(
        f"warehouse-projection-{digest}", digest, jan, warehouse_id.strip(), opening,
        sum((day.forecast_demand_cases for day in days[:7]), Decimal("0")),
        cumulative, first_shortage, tuple(days), inventory_snapshot_id,
        pilot_scope_version, identity_bridge_version, forecast_run_id, forecast_origin_date,
        calculation_at.astimezone(UTC),
    )
