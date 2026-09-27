"""ProjectionとFEFOの検証値をShadow専用画面のread modelへ変換。"""

from __future__ import annotations

from datetime import datetime

from ..expiry_simulation import build_expiry_policy
from ..inventory_foundation.domain import canonical_decimal


class FieldShadowPreviewService:
    def __init__(self, expiry_service):
        self.expiry_service = expiry_service

    def preview(
        self, *, calculation_at: datetime, pilot_scope_version: str,
        identity_bridge_version: str, forecast_run_id: str,
        minimum_remaining_days: int, attention_days: int,
        policy_confirmed_by: str, policy_reason: str,
        policy_confirmed_at: datetime,
    ) -> dict:
        policy = build_expiry_policy(
            minimum_remaining_days=minimum_remaining_days,
            attention_days=attention_days, confirmed_by=policy_confirmed_by,
            reason=policy_reason, confirmed_at=policy_confirmed_at,
        )
        batch = self.expiry_service.calculate(
            calculation_at=calculation_at, pilot_scope_version=pilot_scope_version,
            identity_bridge_version=identity_bridge_version,
            forecast_run_id=forecast_run_id, policy=policy,
        )
        simulations = {
            (item.jan, item.warehouse_id): item for item in batch.simulations
        }
        rows = []
        for projection in batch.warehouse_projections:
            simulation = simulations[(projection.jan, projection.warehouse_id)]
            days = [
                {
                    "business_date": gross.business_date.isoformat(),
                    "forecast_demand_cases": canonical_decimal(gross.forecast_demand_cases),
                    "gross_remaining_cases": canonical_decimal(gross.gross_remaining_cases),
                    "fefo_ending_usable_cases": canonical_decimal(fefo.ending_usable_cases),
                    "fefo_unmet_cases": canonical_decimal(fefo.unmet_cases),
                    "unconsumed_by_cutoff_cases": canonical_decimal(
                        fefo.unconsumed_by_cutoff_cases
                    ),
                }
                for gross, fefo in zip(projection.days, simulation.days, strict=True)
            ]
            rows.append({
                "jan": projection.jan,
                "warehouse_id": projection.warehouse_id,
                "current_warehouse_cases": canonical_decimal(projection.starting_inventory_cases),
                "forecast_7_days_cases": canonical_decimal(projection.demand_7_days_cases),
                "forecast_14_days_cases": canonical_decimal(projection.demand_14_days_cases),
                "first_gross_shortage_date": (
                    None if projection.first_shortage_date is None
                    else projection.first_shortage_date.isoformat()
                ),
                "gross_shortfall_14_days_cases": canonical_decimal(
                    projection.days[-1].cumulative_shortfall_cases
                ),
                "fefo_unmet_14_days_cases": canonical_decimal(simulation.unmet_demand_cases),
                "unconsumed_by_cutoff_14_days_cases": canonical_decimal(
                    simulation.unconsumed_by_cutoff_cases
                ),
                "attention_after_first_day_cases": canonical_decimal(
                    simulation.days[0].attention_cases
                ),
                "system_reference_quantity": None,
                "reference_case_id": None,
                "projection_id": projection.projection_id,
                "simulation_id": simulation.simulation_id,
                "days": days,
            })
        return {
            "mode": "SHADOW",
            "notice": "参考値・検証中・出荷指示ではありません",
            "reference_quantity_status": "NOT_CALCULATED_POLICY_UNCONFIRMED",
            "calculation_at": batch.calculation_at.isoformat(),
            "snapshot_at": batch.snapshot_at.isoformat(),
            "snapshot_known_at": batch.snapshot_known_at.isoformat(),
            "forecast_cutoff_at": batch.forecast_cutoff_at.isoformat(),
            "forecast_finished_at": batch.forecast_finished_at.isoformat(),
            "inventory_snapshot_id": batch.inventory_snapshot_id,
            "pilot_scope_version": batch.pilot_scope_version,
            "identity_bridge_version": batch.identity_bridge_version,
            "forecast_run_id": batch.forecast_run_id,
            "policy_version": batch.policy.policy_version,
            "minimum_remaining_days": batch.policy.minimum_remaining_days,
            "attention_days": batch.policy.attention_days,
            "rows": rows,
        }
