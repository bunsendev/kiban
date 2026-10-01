from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from forecast_provider.inventory_foundation.contracts import RecommendationBasis
from forecast_provider.shipment_decision import (
    FactorySupply,
    ProductionPlan,
    RouteLeadTimePolicy,
    SafetyStockPolicy,
    WarehouseDemand,
    build_shipment_recommendations,
)


def route(policy_id: str, factory: str, warehouse: str, hours: int):
    return RouteLeadTimePolicy(
        policy_id, policy_id, "locations-v1", factory, warehouse,
        hours, hours, hours, RecommendationBasis.STANDARD, date(2026, 1, 1),
    )


def test_arrival_inventory_safety_stock_unit_and_factory_constraint():
    calculation_at = datetime(2026, 1, 1, tzinfo=UTC)
    jan = "4901234567894"
    result = build_shipment_recommendations(
        calculation_at=calculation_at,
        demands=(WarehouseDemand(
            jan, "W01", Decimal("5"),
            tuple((date(2026, 1, 2) + timedelta(days=offset), Decimal("4"))
                  for offset in range(6)),
            date(2026, 1, 3), True,
        ),),
        routes=(RouteLeadTimePolicy(
            "route-v1", "route-v1", "locations-v1", "F01", "W01",
            12, 24, 36, RecommendationBasis.MAXIMUM, date(2026, 1, 1),
        ),),
        safety_policies=(SafetyStockPolicy("safety-v1", "W01", 2, Decimal("5")),),
        factory_supplies=(FactorySupply(
            "factory-snapshot-v1", calculation_at, "F01", jan, Decimal("10")
        ),),
        production_plans=(
            ProductionPlan(
                "completed", "plans-v1", "F01", jan,
                calculation_at - timedelta(hours=1), Decimal("5"),
            ),
            ProductionPlan(
                "future", "plans-v1", "F01", jan,
                calculation_at + timedelta(hours=1), Decimal("99"),
            ),
        ),
    )

    item = result["recommendations"][0]
    assert item["selected_lead_time_hours"] == 36
    assert item["arrival_demand_cases"] == "4"
    assert item["arrival_time_inventory_cases"] == "1"
    assert item["safety_stock_demand_cases"] == "8"
    assert item["required_replenishment_cases"] == "10"
    assert item["factory_available_before_cases"] == "15"
    assert item["recommended_shipment_cases"] == "10"
    assert item["unmet_cases"] == "0"
    assert item["risk_flags"] == ["STOCKOUT_RISK", "EXPIRY_RISK"]


def test_shared_factory_supply_is_allocated_in_shortage_priority_order():
    calculation_at = datetime(2026, 1, 1, tzinfo=UTC)
    jan = "4901234567894"
    common = {
        "calculation_at": calculation_at,
        "routes": (
            route("r1", "F01", "W01", 12),
            route("r2", "F01", "W02", 12),
        ),
        "safety_policies": (
            SafetyStockPolicy("s1", "W01", 1, Decimal("1")),
            SafetyStockPolicy("s2", "W02", 1, Decimal("1")),
        ),
        "factory_supplies": (FactorySupply(
            "stock", calculation_at, "F01", jan, Decimal("5")
        ),),
    }
    demands = (
        WarehouseDemand(jan, "W02", Decimal("0"), ((date(2026, 1, 2), Decimal("5")),),
                        date(2026, 1, 2)),
        WarehouseDemand(jan, "W01", Decimal("0"), ((date(2026, 1, 2), Decimal("5")),),
                        date(2026, 1, 2)),
    )

    result = build_shipment_recommendations(demands=demands, **common)

    assert [item["warehouse_id"] for item in result["recommendations"]] == ["W01", "W02"]
    assert result["recommendations"][0]["recommended_shipment_cases"] == "5"
    assert result["recommendations"][1]["recommended_shipment_cases"] == "0"
    assert "FACTORY_SUPPLY_SHORTAGE" in result["recommendations"][1]["risk_flags"]


def test_missing_versioned_inputs_remain_explicit_blockers():
    calculation_at = datetime(2026, 1, 1, tzinfo=UTC)
    result = build_shipment_recommendations(
        calculation_at=calculation_at,
        demands=(WarehouseDemand(
            "4901234567894", "W01", Decimal("1"),
            ((date(2026, 1, 2), Decimal("1")),), None,
        ),),
        routes=(), safety_policies=(), factory_supplies=(),
    )
    assert result["recommendations"] == []
    assert result["blockers"] == [{
        "jan": "4901234567894", "warehouse_id": "W01",
        "code": "ROUTE_OR_SAFETY_POLICY_MISSING",
    }]


def test_expiry_loss_holds_automatic_shipment_for_manual_review():
    calculation_at = datetime(2026, 1, 1, tzinfo=UTC)
    jan = "4901234567894"
    result = build_shipment_recommendations(
        calculation_at=calculation_at,
        demands=(WarehouseDemand(
            jan, "W01", Decimal("0"),
            ((date(2026, 1, 2), Decimal("5")),), date(2026, 1, 2), True,
            Decimal("2"),
        ),),
        routes=(route("r1", "F01", "W01", 12),),
        safety_policies=(SafetyStockPolicy("s1", "W01", 1, Decimal("1")),),
        factory_supplies=(FactorySupply("stock", calculation_at, "F01", jan, Decimal("9")),),
    )
    item = result["recommendations"][0]
    assert item["required_replenishment_cases"] == "5"
    assert item["recommended_shipment_cases"] == "0"
    assert item["unmet_cases"] == "5"
    assert item["manual_review_required"] is True
    assert "EXPIRY_SHIPMENT_HOLD" in item["risk_flags"]
