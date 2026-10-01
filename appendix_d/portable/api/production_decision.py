"""Portable adapter for auditable arrival-time shipment recommendations."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from forecast_provider.expiry_simulation import ExpirySimulationService, build_expiry_policy
from forecast_provider.inventory_foundation.contracts import RecommendationBasis
from forecast_provider.shipment_decision import (
    FactorySupply,
    ProductionPlan,
    RouteLeadTimePolicy,
    SafetyStockPolicy,
    WarehouseDemand,
    build_shipment_recommendations,
)

from .formal_shipment_daily import canonical_json, sha256
from .production_handoff import ProductionHandoffError
from .production_projection import PortableProductionProjection


class PortableShipmentDecision:
    """Bind one immutable daily summary to explicit, versioned supply policies."""

    def __init__(self, paths, projection: PortableProductionProjection) -> None:
        self.projection = projection
        self.root = paths.formal_forecast / "ProductionDecisions"
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, build_id: str, summary_key: str, payload: dict) -> dict:
        request = _request(payload)
        summary = self.projection.get_summary(summary_key)
        if summary["build_id"] != build_id:
            raise ProductionHandoffError("日次サマリーと正式予測buildが一致しません")
        request_key = sha256(canonical_json({
            "format": "portable-shipment-decision-request-v1",
            "build_id": build_id,
            "summary_sha256": summary["summary_sha256"],
            **request,
        }))
        target = self.root / f"{request_key}.json"
        if target.is_file():
            return _verified(target, request_key)

        calculation_at = _datetime(summary["calculation_at"], "calculation_at")
        context = self.projection.context(build_id)
        expiry = summary["expiry_policy"]
        expiry_policy = build_expiry_policy(
            minimum_remaining_days=expiry["minimum_remaining_days"],
            attention_days=expiry["attention_days"],
            confirmed_by=expiry["confirmed_by"],
            reason=expiry["reason"],
            confirmed_at=_datetime(expiry["confirmed_at"], "confirmed_at"),
        )
        expiry_service = ExpirySimulationService(context["projection_service"])
        risk_by_pair = {
            (item["jan"], item["warehouse_id"]): item
            for item in summary["rows"]
        }
        demands = []
        blockers = list(summary["blockers"])
        for entry in context["scopes"]:
            try:
                batch = expiry_service.calculate(
                    calculation_at=calculation_at,
                    pilot_scope_version=entry["pilot_scope_version"],
                    identity_bridge_version=context["manifest"]["identity_bridge_version"],
                    forecast_run_id=context["receipt"]["run_id"],
                    policy=expiry_policy,
                )
            except ValueError as exc:
                blockers.append({**entry, "code": getattr(exc, "code", type(exc).__name__)})
                continue
            for value in batch.warehouse_projections:
                risk = risk_by_pair.get((value.jan, value.warehouse_id), {})
                demands.append(WarehouseDemand(
                    jan=value.jan,
                    warehouse_id=value.warehouse_id,
                    starting_inventory_cases=value.starting_inventory_cases,
                    daily_demand=tuple(
                        (day.business_date, day.forecast_demand_cases) for day in value.days
                    ),
                    first_shortage_date=value.first_shortage_date,
                    expiry_risk="EXPIRY_RISK" in risk.get("risk_flags", []),
                    expiry_unconsumed_cases=Decimal(
                        risk.get("unconsumed_by_cutoff_cases", "0")
                    ),
                ))

        try:
            decision = build_shipment_recommendations(
                calculation_at=calculation_at,
                demands=tuple(demands),
                routes=tuple(_route(item) for item in request["routes"]),
                safety_policies=tuple(
                    SafetyStockPolicy(
                        item["policy_version"], item["warehouse_id"],
                        item["coverage_days"], Decimal(item["shipment_unit_cases"]),
                    )
                    for item in request["safety_stock_policies"]
                ),
                factory_supplies=tuple(
                    FactorySupply(
                        item["snapshot_id"], _datetime(item["snapshot_at"], "snapshot_at"),
                        item["factory_id"], item["jan"], Decimal(item["inventory_cases"]),
                    )
                    for item in request["factory_supplies"]
                ),
                production_plans=tuple(
                    ProductionPlan(
                        item["plan_id"], item["plan_version"], item["factory_id"],
                        item["jan"], _datetime(item["completion_at"], "completion_at"),
                        Decimal(item["quantity_cases"]),
                    )
                    for item in request["production_plans"]
                ),
            )
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ProductionHandoffError(str(exc)) from exc

        result = {
            **decision,
            "request_key": request_key,
            "build_id": build_id,
            "daily_summary_id": summary["summary_id"],
            "daily_summary_sha256": summary["summary_sha256"],
            "mode": "SHADOW",
            "notice": "参考値・検証中です。担当者の確認なしに出荷指示へ使用しないでください。",
            "actor": request["actor"],
            "reason": request["reason"],
            "source_blockers": blockers,
            "input_versions": {
                "route_policy_versions": sorted({
                    item["policy_version"] for item in request["routes"]
                }),
                "safety_stock_policy_versions": sorted({
                    item["policy_version"] for item in request["safety_stock_policies"]
                }),
                "factory_snapshot_ids": sorted({
                    item["snapshot_id"] for item in request["factory_supplies"]
                }),
                "production_plan_versions": sorted({
                    item["plan_version"] for item in request["production_plans"]
                }),
            },
        }
        result["result_sha256"] = sha256(canonical_json(result))
        _atomic_json(target, result)
        return result


def _request(payload: dict) -> dict:
    actor = str(payload.get("actor") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if not actor or not reason or payload.get("confirm_decision_inputs") is not True:
        raise ProductionHandoffError("確認者、確認理由、Decision Engine入力の確認が必要です")
    names = ("routes", "safety_stock_policies", "factory_supplies", "production_plans")
    if any(not isinstance(payload.get(name), list) for name in names):
        raise ProductionHandoffError(
            "route、安全在庫、工場在庫、生産予定の入力形式を確認してください"
        )
    if (
        not payload["routes"]
        or not payload["safety_stock_policies"]
        or not payload["factory_supplies"]
    ):
        raise ProductionHandoffError("route、安全在庫、工場在庫は1件以上必要です")
    return {
        "actor": actor,
        "reason": reason,
        "confirm_decision_inputs": True,
        **{name: payload[name] for name in names},
    }


def _route(item: dict) -> RouteLeadTimePolicy:
    return RouteLeadTimePolicy(
        policy_id=item["policy_id"],
        policy_version=item["policy_version"],
        location_master_version=item["location_master_version"],
        factory_location_id=item["factory_location_id"],
        warehouse_location_id=item["warehouse_location_id"],
        minimum_hours=item["minimum_hours"],
        standard_hours=item["standard_hours"],
        maximum_hours=item["maximum_hours"],
        recommendation_basis=RecommendationBasis(item["recommendation_basis"]),
        effective_from=datetime.fromisoformat(item["effective_from"]).date(),
        effective_to=(
            None if item.get("effective_to") is None
            else datetime.fromisoformat(item["effective_to"]).date()
        ),
    )


def _datetime(value: str, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductionHandoffError(f"{label}はtimezone付きISO日時で指定してください") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ProductionHandoffError(f"{label}はtimezone付きISO日時で指定してください")
    return result


def _verified(path: Path, request_key: str) -> dict:
    try:
        result = json.loads(path.read_bytes())
        expected = result.pop("result_sha256")
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProductionHandoffError("出荷推奨結果の整合性を確認できません") from exc
    actual = sha256(canonical_json(result))
    result["result_sha256"] = expected
    if actual != expected or result.get("request_key") != request_key:
        raise ProductionHandoffError("出荷推奨結果の整合性を確認できません")
    return result


def _atomic_json(path: Path, value: dict) -> None:
    content = canonical_json(value)
    temporary = path.with_name(f".{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)
