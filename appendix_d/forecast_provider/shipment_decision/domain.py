"""Versioned inputs for deterministic shipment recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from forecast_provider.inventory_foundation.domain import (
    canonical_datetime,
    canonical_decimal,
    validate_jan,
)


def quantity(value: Decimal | int | str, label: str) -> Decimal:
    result = Decimal(canonical_decimal(value))
    if result < 0:
        raise ValueError(f"{label}は0以上です")
    return result


def required(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label}は必須です")
    return normalized


def aware(value: datetime, label: str) -> datetime:
    canonical_datetime(value, label)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class SafetyStockPolicy:
    policy_version: str
    warehouse_id: str
    coverage_days: int
    shipment_unit_cases: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_version", required(self.policy_version, "policy_version"))
        object.__setattr__(self, "warehouse_id", required(self.warehouse_id, "warehouse_id"))
        if isinstance(self.coverage_days, bool) or not 0 <= self.coverage_days <= 28:
            raise ValueError("安全在庫日数は0〜28日の整数で指定してください")
        unit = quantity(self.shipment_unit_cases, "shipment_unit_cases")
        if unit <= 0:
            raise ValueError("shipment_unit_casesは0より大きい値です")
        object.__setattr__(self, "shipment_unit_cases", unit)


@dataclass(frozen=True)
class FactorySupply:
    snapshot_id: str
    snapshot_at: datetime
    factory_id: str
    jan: str
    inventory_cases: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", required(self.snapshot_id, "snapshot_id"))
        object.__setattr__(self, "factory_id", required(self.factory_id, "factory_id"))
        object.__setattr__(self, "jan", validate_jan(self.jan))
        object.__setattr__(self, "snapshot_at", aware(self.snapshot_at, "snapshot_at"))
        object.__setattr__(
            self, "inventory_cases", quantity(self.inventory_cases, "inventory_cases")
        )


@dataclass(frozen=True)
class ProductionPlan:
    plan_id: str
    plan_version: str
    factory_id: str
    jan: str
    completion_at: datetime
    quantity_cases: Decimal

    def __post_init__(self) -> None:
        for name in ("plan_id", "plan_version", "factory_id"):
            object.__setattr__(self, name, required(getattr(self, name), name))
        object.__setattr__(self, "jan", validate_jan(self.jan))
        object.__setattr__(self, "completion_at", aware(self.completion_at, "completion_at"))
        object.__setattr__(self, "quantity_cases", quantity(self.quantity_cases, "quantity_cases"))


@dataclass(frozen=True)
class WarehouseDemand:
    jan: str
    warehouse_id: str
    starting_inventory_cases: Decimal
    daily_demand: tuple[tuple[date, Decimal], ...]
    first_shortage_date: date | None
    expiry_risk: bool = False
    expiry_unconsumed_cases: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        object.__setattr__(self, "jan", validate_jan(self.jan))
        object.__setattr__(self, "warehouse_id", required(self.warehouse_id, "warehouse_id"))
        object.__setattr__(
            self, "starting_inventory_cases",
            quantity(self.starting_inventory_cases, "starting_inventory_cases"),
        )
        if not self.daily_demand:
            raise ValueError("daily_demandは1日以上必要です")
        previous = None
        normalized = []
        for business_date, raw in self.daily_demand:
            if previous is not None and business_date <= previous:
                raise ValueError("daily_demandの日付は昇順かつ重複なしで指定してください")
            normalized.append((business_date, quantity(raw, "forecast_demand_cases")))
            previous = business_date
        object.__setattr__(self, "daily_demand", tuple(normalized))
        object.__setattr__(
            self,
            "expiry_unconsumed_cases",
            quantity(self.expiry_unconsumed_cases, "expiry_unconsumed_cases"),
        )
