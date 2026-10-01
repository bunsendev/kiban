"""Pure allocation using inventory at each route's arrival time."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from zoneinfo import ZoneInfo

from forecast_provider.inventory_foundation.domain import canonical_decimal
from forecast_provider.inventory_foundation.locations import RouteLeadTimePolicy

from .domain import (
    FactorySupply,
    ProductionPlan,
    SafetyStockPolicy,
    WarehouseDemand,
    aware,
)

JST = ZoneInfo("Asia/Tokyo")


def _ceil_unit(value: Decimal, unit: Decimal) -> Decimal:
    if value <= 0:
        return Decimal("0")
    return (value / unit).to_integral_value(rounding=ROUND_CEILING) * unit


def _canonical_payload(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def build_shipment_recommendations(
    *,
    calculation_at: datetime,
    demands: tuple[WarehouseDemand, ...],
    routes: tuple[RouteLeadTimePolicy, ...],
    safety_policies: tuple[SafetyStockPolicy, ...],
    factory_supplies: tuple[FactorySupply, ...],
    production_plans: tuple[ProductionPlan, ...] = (),
) -> dict:
    """Allocate currently dispatchable factory supply without inventing missing inputs."""

    calculation_at = aware(calculation_at, "calculation_at")
    route_by_warehouse = {item.warehouse_location_id: item for item in routes}
    safety_by_warehouse = {item.warehouse_id: item for item in safety_policies}
    if len(route_by_warehouse) != len(routes) or len(safety_by_warehouse) != len(safety_policies):
        raise ValueError("warehouseごとのrouteまたは安全在庫policyが重複しています")
    supply_by_key = {(item.factory_id, item.jan): item for item in factory_supplies}
    if len(supply_by_key) != len(factory_supplies):
        raise ValueError("工場在庫はfactory×JANごとに1件です")
    plans_by_key: dict[tuple[str, str], list[ProductionPlan]] = {}
    for plan in production_plans:
        plans_by_key.setdefault((plan.factory_id, plan.jan), []).append(plan)

    candidates = []
    blockers = []
    for demand in demands:
        route = route_by_warehouse.get(demand.warehouse_id)
        safety = safety_by_warehouse.get(demand.warehouse_id)
        if route is None or safety is None:
            blockers.append({
                "jan": demand.jan, "warehouse_id": demand.warehouse_id,
                "code": "ROUTE_OR_SAFETY_POLICY_MISSING",
            })
            continue
        calculation_date = calculation_at.astimezone(JST).date()
        if (
            calculation_date < route.effective_from
            or (route.effective_to is not None and calculation_date > route.effective_to)
        ):
            blockers.append({
                "jan": demand.jan, "warehouse_id": demand.warehouse_id,
                "code": "ROUTE_POLICY_NOT_EFFECTIVE",
            })
            continue
        supply = supply_by_key.get((route.factory_location_id, demand.jan))
        if supply is None:
            blockers.append({
                "jan": demand.jan, "warehouse_id": demand.warehouse_id,
                "factory_id": route.factory_location_id,
                "code": "FACTORY_INVENTORY_MISSING",
            })
            continue
        if supply.snapshot_at > calculation_at:
            blockers.append({
                "jan": demand.jan, "warehouse_id": demand.warehouse_id,
                "factory_id": route.factory_location_id,
                "code": "FACTORY_INVENTORY_NOT_KNOWN_AS_OF",
            })
            continue
        arrival_at = calculation_at + timedelta(hours=route.selected_lead_time_hours)
        arrival_date = arrival_at.astimezone(JST).date()
        arrival_demand = sum(
            (value for day, value in demand.daily_demand if day <= arrival_date), Decimal("0")
        )
        arrival_inventory = demand.starting_inventory_cases - arrival_demand
        safety_end = arrival_date + timedelta(days=safety.coverage_days)
        safety_demand = sum(
            (
                value for day, value in demand.daily_demand
                if arrival_date < day <= safety_end
            ),
            Decimal("0"),
        )
        required = _ceil_unit(max(Decimal("0"), safety_demand - arrival_inventory),
                              safety.shipment_unit_cases)
        candidates.append({
            "demand": demand,
            "route": route,
            "safety": safety,
            "supply": supply,
            "arrival_at": arrival_at,
            "arrival_inventory": arrival_inventory,
            "arrival_demand": arrival_demand,
            "safety_demand": safety_demand,
            "required": required,
        })

    remaining = {
        key: supply.inventory_cases + sum(
            (plan.quantity_cases for plan in plans_by_key.get(key, ())
             if plan.completion_at <= calculation_at), Decimal("0")
        )
        for key, supply in supply_by_key.items()
    }
    candidates.sort(key=lambda item: (
        item["demand"].first_shortage_date is None,
        item["demand"].first_shortage_date or item["demand"].daily_demand[-1][0],
        -item["route"].selected_lead_time_hours,
        item["demand"].warehouse_id,
        item["demand"].jan,
    ))
    recommendations = []
    for item in candidates:
        demand = item["demand"]
        route = item["route"]
        key = (route.factory_location_id, demand.jan)
        available_before = remaining[key]
        expiry_hold = demand.expiry_unconsumed_cases > 0
        recommended = (
            Decimal("0") if expiry_hold else min(item["required"], available_before)
        )
        remaining[key] -= recommended
        unmet = item["required"] - recommended
        risks = []
        if item["arrival_inventory"] < 0 or demand.first_shortage_date is not None:
            risks.append("STOCKOUT_RISK")
        if demand.expiry_risk:
            risks.append("EXPIRY_RISK")
        if expiry_hold:
            risks.append("EXPIRY_SHIPMENT_HOLD")
        if unmet > 0:
            risks.append("FACTORY_SUPPLY_SHORTAGE")
        if expiry_hold:
            reason = "期限内消化困難在庫があるため自動配分を保留"
        elif item["required"] > 0:
            reason = "到着時点在庫と安全在庫需要から補充が必要"
        else:
            reason = "到着時点在庫で安全在庫需要を満たす"
        recommendations.append({
            "jan": demand.jan,
            "factory_id": route.factory_location_id,
            "warehouse_id": demand.warehouse_id,
            "arrival_at": item["arrival_at"].isoformat(),
            "selected_lead_time_hours": route.selected_lead_time_hours,
            "arrival_demand_cases": canonical_decimal(item["arrival_demand"]),
            "arrival_time_inventory_cases": canonical_decimal(item["arrival_inventory"]),
            "safety_stock_demand_cases": canonical_decimal(item["safety_demand"]),
            "required_replenishment_cases": canonical_decimal(item["required"]),
            "factory_available_before_cases": canonical_decimal(available_before),
            "recommended_shipment_cases": canonical_decimal(recommended),
            "unmet_cases": canonical_decimal(unmet),
            "expiry_unconsumed_cases": canonical_decimal(
                demand.expiry_unconsumed_cases
            ),
            "manual_review_required": expiry_hold,
            "shipment_unit_cases": canonical_decimal(item["safety"].shipment_unit_cases),
            "route_policy_version": route.policy_version,
            "safety_stock_policy_version": item["safety"].policy_version,
            "factory_snapshot_id": item["supply"].snapshot_id,
            "reason": reason,
            "risk_flags": risks,
        })

    payload = {
        "format": "shipment-recommendation-v1",
        "calculation_at": calculation_at.isoformat(),
        "recommendations": recommendations,
        "blockers": blockers,
        "factory_remaining_cases": [
            {"factory_id": key[0], "jan": key[1], "quantity_cases": canonical_decimal(value)}
            for key, value in sorted(remaining.items())
        ],
    }
    digest = hashlib.sha256(_canonical_payload(payload)).hexdigest()
    return {**payload, "decision_id": f"shipment-decision-{digest}", "content_sha256": digest}
