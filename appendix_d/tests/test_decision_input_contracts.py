import io
import zipfile

import pytest

from portable.api.decision_input_contracts import (
    DecisionInputError,
    parse_archive,
    template_zip,
)
from portable.api.decision_input_package import _summary_issues


def archive(files: dict[str, str]) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, content in files.items():
            output.writestr(name, content.encode("utf-8-sig"))
    return target.getvalue()


def valid_files() -> dict[str, str]:
    return {
        "factory_inventory.csv": (
            "factory_snapshot_id,snapshot_at,factory_id,jan,inventory_cases\n"
            "stock-v1,2026-01-01T00:00:00+00:00,F01,4901234567894,20\n"
        ),
        "routes.csv": (
            "policy_id,policy_version,location_master_version,factory_location_id,"
            "warehouse_location_id,minimum_hours,standard_hours,maximum_hours,"
            "recommendation_basis,effective_from,effective_to\n"
            "route-1,routes-v1,locations-v1,F01,W01,12,24,36,MAXIMUM,2026-01-01,\n"
        ),
        "safety_stock.csv": (
            "policy_version,warehouse_id,coverage_days,shipment_unit_cases\n"
            "safety-v1,W01,3,1\n"
        ),
        "production_plans.csv": (
            "plan_id,plan_version,factory_id,jan,completion_at,quantity_cases\n"
            "plan-1,plans-v1,F01,4901234567894,2026-01-01T00:00:00+00:00,5\n"
        ),
    }


def test_formal_decision_csv_archive_normalizes_versioned_inputs():
    result = parse_archive(archive(valid_files()))

    assert result["quarantines"] == []
    assert result["accepted"]["factory_supplies"][0]["inventory_cases"] == "20"
    assert result["accepted"]["routes"][0]["maximum_hours"] == 36
    assert result["accepted"]["safety_stock_policies"][0]["coverage_days"] == 3
    assert result["accepted"]["production_plans"][0]["quantity_cases"] == "5"
    assert len(result["sources"]) == 4


def test_invalid_rows_are_quarantined_without_becoming_zero():
    files = valid_files()
    files["factory_inventory.csv"] += (
        "stock-v1,2026-01-01T00:00:00+00:00,F01,4901234567895,not-a-number\n"
    )
    result = parse_archive(archive(files))

    assert len(result["accepted"]["factory_supplies"]) == 1
    assert result["quarantines"][0]["filename"] == "factory_inventory.csv"
    assert result["quarantines"][0]["row_number"] == 3
    assert result["quarantines"][0]["reason_code"] == "ROW_CONTRACT_INVALID"
    assert len(result["quarantines"][0]["row_sha256"]) == 64


def test_unknown_or_nested_files_are_rejected():
    files = valid_files()
    files["nested/unknown.csv"] = "a\n1\n"
    with pytest.raises(DecisionInputError, match="ZIP直下"):
        parse_archive(archive(files))


def test_summary_template_contains_four_utf8_csv_files():
    raw = template_zip(["W02", "W01"], ["4901234567894"])
    with zipfile.ZipFile(io.BytesIO(raw)) as value:
        assert sorted(value.namelist()) == [
            "factory_inventory.csv", "production_plans.csv", "routes.csv",
            "safety_stock.csv",
        ]
        assert "W01" in value.read("routes.csv").decode("utf-8-sig")


def test_daily_summary_scope_reports_missing_and_outside_inputs():
    accepted = parse_archive(archive(valid_files()))["accepted"]
    accepted["factory_supplies"].append({
        "snapshot_id": "stock-v2", "snapshot_at": "2026-01-01T00:00:00+00:00",
        "factory_id": "F01", "jan": "4909999999999", "inventory_cases": "1",
    })
    accepted["production_plans"].append({
        "plan_id": "plan-2", "plan_version": "plans-v1", "factory_id": "F02",
        "jan": "4901234567894", "completion_at": "2026-01-01T00:00:00+00:00",
        "quantity_cases": "1",
    })
    accepted["safety_stock_policies"].append({
        "policy_version": "safety-v1", "warehouse_id": "W99",
        "coverage_days": 3, "shipment_unit_cases": "1",
    })

    issues = _summary_issues(
        {
            "warehouses": [{"warehouse_id": "W01"}, {"warehouse_id": "W02"}],
            "rows": [{"jan": "4901234567894"}, {"jan": "4901234567895"}],
        },
        accepted,
    )
    codes = {item["code"] for item in issues}

    assert "ROUTE_POLICY_MISSING" in codes
    assert "FACTORY_INVENTORY_MISSING" in codes
    assert "FACTORY_INVENTORY_OUTSIDE_DAILY_SUMMARY" in codes
    assert "PRODUCTION_PLAN_FACTORY_INVENTORY_MISSING" in codes
    assert "SAFETY_POLICY_OUTSIDE_DAILY_SUMMARY" in codes
