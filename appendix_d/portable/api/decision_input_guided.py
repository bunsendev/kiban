"""Operator-friendly adapter for the formal Decision input ZIP contract."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation

from .decision_input_contracts import SCHEMAS, DecisionInputError
from .formal_shipment_daily import canonical_json, sha256


def requirements(summary: dict) -> dict:
    """List values requiring a business decision without inventing defaults."""
    warehouses = sorted({item["warehouse_id"] for item in summary["warehouses"]})
    jans = sorted({item["jan"] for item in summary["rows"]})
    return {
        "format": "portable-guided-decision-requirements-v1",
        "daily_summary_id": summary["summary_id"],
        "daily_summary_sha256": summary["summary_sha256"],
        "calculation_at": summary["calculation_at"],
        "warehouses": warehouses,
        "jans": jans,
        "required_factory_inventory_rows": len(jans),
        "required_route_rows": len(warehouses),
        "required_safety_stock_rows": len(warehouses),
        "production_plans_optional": True,
    }


def package_payload(summary: dict, payload: dict) -> dict:
    actor = str(payload.get("actor") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    factory_id = str(payload.get("factory_id") or "").strip()
    policy_version = str(payload.get("policy_version") or "").strip()
    snapshot_at = str(payload.get("snapshot_at") or "").strip()
    if (
        not actor or not reason or not factory_id or not policy_version or not snapshot_at
        or payload.get("confirm_decision_inputs") is not True
    ):
        raise DecisionInputError(
            "確認者、理由、工場、policy版、工場在庫日時、正式入力の確認が必要です"
        )

    expected = requirements(summary)
    inventory = payload.get("factory_inventory")
    if not isinstance(inventory, list):
        raise DecisionInputError("商品ごとの工場在庫（箱）を入力してください")
    by_jan: dict[str, str] = {}
    for item in inventory:
        if not isinstance(item, dict):
            raise DecisionInputError("商品ごとの工場在庫（箱）を確認してください")
        jan = str(item.get("jan") or "").strip()
        quantity = str(item.get("inventory_cases") or "").strip()
        if not jan or not quantity or jan in by_jan:
            raise DecisionInputError("商品ごとの工場在庫を重複なく入力してください")
        try:
            if Decimal(quantity) < 0:
                raise DecisionInputError("工場在庫は0以上で入力してください")
        except InvalidOperation as exc:
            raise DecisionInputError("工場在庫は数値で入力してください") from exc
        by_jan[jan] = quantity
    expected_jans = set(expected["jans"])
    if set(by_jan) != expected_jans:
        missing = len(expected_jans - set(by_jan))
        outside = len(set(by_jan) - expected_jans)
        raise DecisionInputError(
            f"対象商品の工場在庫を全件入力してください（不足{missing}件、対象外{outside}件）"
        )

    route = payload.get("route")
    safety = payload.get("safety_stock")
    if not isinstance(route, dict) or not isinstance(safety, dict):
        raise DecisionInputError("配送時間、安全在庫、出荷単位を入力してください")
    production = payload.get("production_plans", [])
    if not isinstance(production, list):
        raise DecisionInputError("生産予定の入力形式を確認してください")

    identity = sha256(canonical_json({
        "summary_sha256": summary["summary_sha256"],
        "factory_id": factory_id,
        "policy_version": policy_version,
        "snapshot_at": snapshot_at,
        "inventory": by_jan,
        "route": route,
        "safety_stock": safety,
        "production_plans": production,
    }))[:20]
    calculation_date = date.fromisoformat(summary["calculation_at"][:10]).isoformat()
    values = {
        "factory_inventory.csv": [
            {
                "factory_snapshot_id": f"guided-{identity}",
                "snapshot_at": snapshot_at,
                "factory_id": factory_id,
                "jan": jan,
                "inventory_cases": by_jan[jan],
            }
            for jan in expected["jans"]
        ],
        "production_plans.csv": [
            {
                "plan_id": str(item.get("plan_id") or "").strip(),
                "plan_version": str(item.get("plan_version") or "").strip(),
                "factory_id": factory_id,
                "jan": str(item.get("jan") or "").strip(),
                "completion_at": str(item.get("completion_at") or "").strip(),
                "quantity_cases": str(item.get("quantity_cases") or "").strip(),
            }
            for item in production
        ],
        "routes.csv": [
            {
                "policy_id": f"guided-route-{identity}-{warehouse}",
                "policy_version": policy_version,
                "location_master_version": str(
                    route.get("location_master_version") or policy_version
                ).strip(),
                "factory_location_id": factory_id,
                "warehouse_location_id": warehouse,
                "minimum_hours": route.get("minimum_hours", ""),
                "standard_hours": route.get("standard_hours", ""),
                "maximum_hours": route.get("maximum_hours", ""),
                "recommendation_basis": route.get("recommendation_basis", ""),
                "effective_from": str(route.get("effective_from") or calculation_date),
                "effective_to": str(route.get("effective_to") or ""),
            }
            for warehouse in expected["warehouses"]
        ],
        "safety_stock.csv": [
            {
                "policy_version": policy_version,
                "warehouse_id": warehouse,
                "coverage_days": safety.get("coverage_days", ""),
                "shipment_unit_cases": safety.get("shipment_unit_cases", ""),
            }
            for warehouse in expected["warehouses"]
        ],
    }
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, headers in SCHEMAS.items():
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\r\n")
            writer.writeheader()
            writer.writerows(values[name])
            archive.writestr(name, stream.getvalue().encode("utf-8-sig"))
    return {
        "actor": actor,
        "reason": reason,
        "confirm_decision_inputs": True,
        "archive": target.getvalue(),
    }
