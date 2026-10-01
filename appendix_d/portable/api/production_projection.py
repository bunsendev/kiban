"""Aggregate immutable Production Run results into warehouse operations views."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from forecast_provider.expiry_simulation import (
    ExpirySimulationBlocked,
    ExpirySimulationService,
    build_expiry_policy,
)
from forecast_provider.inventory_foundation.domain import canonical_decimal
from forecast_provider.warehouse_projection import ProjectionBlocked, WarehouseProjectionService

from .formal_forecast_pipeline import PortableFormalForecastPipeline
from .formal_pipeline import PortableFormalPipeline
from .formal_shipment_daily import canonical_json, sha256
from .production_handoff import PortableProductionHandoff, ProductionHandoffError


class PortableProductionProjection:
    """Build per-scope projections and an auditable cross-warehouse summary."""

    def __init__(self, paths, handoff: PortableProductionHandoff) -> None:
        self.paths = paths
        self.handoff = handoff
        self.summary_root = paths.formal_forecast / "ProductionSummaries"
        self.summary_root.mkdir(parents=True, exist_ok=True)

    def projection(self, build_id: str) -> dict:
        context = self.context(build_id)
        calculation_at = datetime.now(UTC)
        projections = []
        scopes = []
        blockers = list(context["blockers"])
        for entry in context["scopes"]:
            try:
                batch = context["projection_service"].calculate(
                    calculation_at=calculation_at,
                    pilot_scope_version=entry["pilot_scope_version"],
                    identity_bridge_version=context["manifest"]["identity_bridge_version"],
                    forecast_run_id=context["receipt"]["run_id"],
                )
            except ProjectionBlocked as exc:
                blockers.append(_blocker(entry, exc.code))
                continue
            scopes.append(_scope_metadata(entry, batch))
            projections.extend(_projection_rows(batch.projections))
        inventory_ids = [item["inventory_snapshot_id"] for item in scopes]
        return {
            "forecast_run_id": context["receipt"]["run_id"],
            "calculation_at": calculation_at.isoformat(),
            "status": _status(projections, blockers),
            "inventory_snapshot_id": inventory_ids[0] if len(inventory_ids) == 1 else None,
            "inventory_snapshot_ids": inventory_ids,
            "scope_results": scopes,
            "blockers": blockers,
            "projections": sorted(
                projections, key=lambda item: (item["warehouse_id"], item["jan"])
            ),
        }

    def daily_summary(self, build_id: str, payload: dict) -> dict:
        request = _summary_request(payload)
        context = self.context(build_id)
        request_key = sha256(canonical_json({
            "format": "portable-daily-summary-request-v1",
            "build_id": build_id,
            "source_receipt_sha256": context["receipt"]["receipt_sha256"],
            **request,
        }))
        target = self.summary_root / f"{request_key}.json"
        if target.is_file():
            return _verified_summary(target, request_key)

        calculation_at = datetime.now(UTC)
        policy = build_expiry_policy(
            minimum_remaining_days=request["minimum_remaining_days"],
            attention_days=request["attention_days"],
            confirmed_by=request["actor"],
            reason=request["reason"],
            confirmed_at=calculation_at,
        )
        expiry_service = ExpirySimulationService(context["projection_service"])
        rows = []
        warehouses = []
        blockers = list(context["blockers"])
        for entry in context["scopes"]:
            try:
                batch = expiry_service.calculate(
                    calculation_at=calculation_at,
                    pilot_scope_version=entry["pilot_scope_version"],
                    identity_bridge_version=context["manifest"]["identity_bridge_version"],
                    forecast_run_id=context["receipt"]["run_id"],
                    policy=policy,
                )
            except (ProjectionBlocked, ExpirySimulationBlocked) as exc:
                blockers.append(_blocker(entry, exc.code))
                continue
            simulations = {
                (item.jan, item.warehouse_id): item for item in batch.simulations
            }
            warehouse_rows = []
            for projection in batch.warehouse_projections:
                simulation = simulations[(projection.jan, projection.warehouse_id)]
                shortage = projection.days[-1].cumulative_shortfall_cases
                attention = simulation.days[0].attention_cases
                expiry_loss = simulation.unconsumed_by_cutoff_cases
                risks = []
                if shortage > 0:
                    risks.append("STOCKOUT_RISK")
                if attention > 0 or expiry_loss > 0:
                    risks.append("EXPIRY_RISK")
                row = {
                    "jan": projection.jan,
                    "warehouse_id": projection.warehouse_id,
                    "current_inventory_cases": canonical_decimal(
                        projection.starting_inventory_cases
                    ),
                    "demand_7d_cases": canonical_decimal(projection.demand_7_days_cases),
                    "demand_14d_cases": canonical_decimal(projection.demand_14_days_cases),
                    "ending_inventory_cases": canonical_decimal(
                        projection.days[-1].gross_remaining_cases
                    ),
                    "shortage_reference_cases": canonical_decimal(shortage),
                    "first_shortage_date": (
                        None if projection.first_shortage_date is None
                        else projection.first_shortage_date.isoformat()
                    ),
                    "expiry_attention_cases": canonical_decimal(attention),
                    "unconsumed_by_cutoff_cases": canonical_decimal(expiry_loss),
                    "risk_flags": risks,
                    "replenishment_candidate": shortage > 0,
                    "replenishment_status": (
                        "REVIEW_SHORTAGE_REFERENCE" if shortage > 0
                        else "NO_SHORTAGE_SIGNAL"
                    ),
                    "projection_id": projection.projection_id,
                    "simulation_id": simulation.simulation_id,
                }
                rows.append(row)
                warehouse_rows.append(row)
            warehouses.append(_warehouse_summary(entry, batch, warehouse_rows))

        result = {
            "format": "portable-daily-operations-summary-v1",
            "request_key": request_key,
            "build_id": build_id,
            "mode": "SHADOW",
            "notice": "参考値・検証中です。正式な出荷指示ではありません。",
            "status": _status(rows, blockers),
            "calculation_at": calculation_at.isoformat(),
            "forecast_run_id": context["receipt"]["run_id"],
            "identity_bridge_version": context["manifest"]["identity_bridge_version"],
            "expiry_policy": {
                "policy_version": policy.policy_version,
                "minimum_remaining_days": policy.minimum_remaining_days,
                "attention_days": policy.attention_days,
                "confirmed_by": policy.confirmed_by,
                "reason": policy.reason,
                "confirmed_at": policy.confirmed_at.isoformat(),
            },
            "replenishment_policy_status": (
                "NOT_CALCULATED_LEAD_TIME_AND_SAFETY_STOCK_POLICY_UNCONFIRMED"
            ),
            "warehouses": sorted(warehouses, key=lambda item: item["warehouse_id"]),
            "rows": sorted(rows, key=lambda item: (item["warehouse_id"], item["jan"])),
            "blockers": blockers,
            "excluded_series": context["receipt"]["blocked_series"],
        }
        result["summary_id"] = f"portable-summary-{sha256(canonical_json(result))}"
        result["summary_sha256"] = sha256(canonical_json(result))
        _atomic_json(target, result)
        return result

    def get_summary(self, request_key: str) -> dict:
        if not request_key or not request_key.isascii() or len(request_key) != 64:
            raise ProductionHandoffError("日次業務サマリーIDを確認してください")
        target = self.summary_root / f"{request_key}.json"
        if not target.is_file():
            raise ProductionHandoffError("日次業務サマリーが見つかりません")
        return _verified_summary(target, request_key)

    def context(self, build_id: str) -> dict:
        manifest, _daily = self.handoff._verified_source(build_id)
        receipt_path = self.handoff._receipt_path(build_id)
        if not receipt_path.is_file():
            raise ProductionHandoffError("Production Forecast Runが登録されていません")
        receipt = self.handoff._verified_receipt(receipt_path)
        pipeline = PortableFormalPipeline(self.paths)
        registration = pipeline.get_registration(manifest["registration_id"])
        scopes = []
        blockers = []
        for item in registration["jobs"]:
            job = pipeline.inventory_store.get_job(item["job_id"])
            if job is None or not job.pilot_scope_version:
                blockers.append(_blocker(item, "PILOT_SCOPE_NOT_FOUND"))
                continue
            scopes.append({
                "source_center": item["source_center"],
                "job_id": item["job_id"],
                "pilot_scope_version": job.pilot_scope_version,
            })
        projection_service = WarehouseProjectionService(
            pipeline.inventory_store,
            pipeline.scope_store,
            PortableFormalForecastPipeline(self.paths).bridge_store,
            self.handoff.service.runs,
        )
        return {
            "manifest": manifest,
            "receipt": receipt,
            "scopes": scopes,
            "blockers": blockers,
            "projection_service": projection_service,
        }


def _summary_request(payload: dict) -> dict:
    actor = str(payload.get("actor") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    minimum = payload.get("minimum_remaining_days")
    attention = payload.get("attention_days")
    if (
        not actor or not reason or payload.get("confirm_expiry_policy") is not True
        or isinstance(minimum, bool) or not isinstance(minimum, int)
        or isinstance(attention, bool) or not isinstance(attention, int)
        or minimum < 0 or attention < 0
    ):
        raise ProductionHandoffError("賞味期限の確認条件、確認者、確認理由を確認してください")
    return {
        "actor": actor,
        "reason": reason,
        "minimum_remaining_days": minimum,
        "attention_days": attention,
    }


def _projection_rows(projections) -> list[dict]:
    return [
        {
            "jan": value.jan,
            "warehouse_id": value.warehouse_id,
            "starting_inventory_cases": canonical_decimal(value.starting_inventory_cases),
            "demand_7d_cases": canonical_decimal(value.demand_7_days_cases),
            "demand_14d_cases": canonical_decimal(value.demand_14_days_cases),
            "ending_inventory_cases": canonical_decimal(value.days[-1].gross_remaining_cases),
            "shortage_cases": canonical_decimal(value.days[-1].cumulative_shortfall_cases),
        }
        for value in projections
    ]


def _scope_metadata(entry: dict, batch) -> dict:
    projections = getattr(batch, "projections", None)
    if projections is None:
        projections = batch.warehouse_projections
    return {
        **entry,
        "inventory_snapshot_id": batch.inventory_snapshot_id,
        "snapshot_at": batch.snapshot_at.isoformat(),
        "forecast_cutoff_at": batch.forecast_cutoff_at.isoformat(),
        "forecast_finished_at": batch.forecast_finished_at.isoformat(),
        "series_count": len(projections),
    }


def _warehouse_summary(entry: dict, batch, rows: list[dict]) -> dict:
    def total(field: str) -> str:
        return canonical_decimal(sum((Decimal(item[field]) for item in rows), Decimal("0")))

    warehouse_ids = {item["warehouse_id"] for item in rows}
    return {
        **_scope_metadata(entry, batch),
        "warehouse_id": next(iter(warehouse_ids)) if len(warehouse_ids) == 1 else "MULTIPLE",
        "current_inventory_cases": total("current_inventory_cases"),
        "demand_7d_cases": total("demand_7d_cases"),
        "demand_14d_cases": total("demand_14d_cases"),
        "shortage_reference_cases": total("shortage_reference_cases"),
        "expiry_attention_cases": total("expiry_attention_cases"),
        "unconsumed_by_cutoff_cases": total("unconsumed_by_cutoff_cases"),
        "shortage_product_count": sum(item["replenishment_candidate"] for item in rows),
        "expiry_risk_product_count": sum("EXPIRY_RISK" in item["risk_flags"] for item in rows),
    }


def _blocker(entry: dict, code: str) -> dict:
    return {
        "source_center": entry.get("source_center"),
        "job_id": entry.get("job_id"),
        "pilot_scope_version": entry.get("pilot_scope_version"),
        "code": code,
    }


def _status(rows: list, blockers: list) -> str:
    if rows and blockers:
        return "PARTIAL"
    if rows:
        return "READY"
    return "BLOCKED"


def _verified_summary(path: Path, request_key: str) -> dict:
    try:
        result = json.loads(path.read_bytes())
        expected = result.pop("summary_sha256")
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProductionHandoffError("日次業務サマリーの整合性を確認できません") from exc
    actual = sha256(canonical_json(result))
    result["summary_sha256"] = expected
    if actual != expected or result.get("request_key") != request_key:
        raise ProductionHandoffError("日次業務サマリーの整合性を確認できません")
    return result


def _atomic_json(path: Path, value: dict) -> None:
    content = canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        if path.read_bytes() != content:
            raise ProductionHandoffError("同じIDの日次業務サマリーが一致しません")
        return
    temporary = path.with_name(f".{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)
