"""承認済みPilot Projectionに同一snapshotの期限bucketを接続する。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from ..warehouse_projection.service import WarehouseProjectionService
from .domain import ExpiryPolicy, ExpirySimulation, simulate_expiry


class ExpirySimulationBlocked(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExpirySimulationBatch:
    inventory_snapshot_id: str
    pilot_scope_version: str
    identity_bridge_version: str
    forecast_run_id: str
    policy: ExpiryPolicy
    calculation_at: datetime
    snapshot_at: datetime
    snapshot_known_at: datetime
    forecast_cutoff_at: datetime
    forecast_finished_at: datetime
    simulations: tuple[ExpirySimulation, ...]


class ExpirySimulationService:
    def __init__(self, projection_service: WarehouseProjectionService):
        self.projection_service = projection_service

    def calculate(
        self, *, calculation_at: datetime, pilot_scope_version: str,
        identity_bridge_version: str, forecast_run_id: str, policy: ExpiryPolicy,
    ) -> ExpirySimulationBatch:
        batch = self.projection_service.calculate(
            calculation_at=calculation_at,
            pilot_scope_version=pilot_scope_version,
            identity_bridge_version=identity_bridge_version,
            forecast_run_id=forecast_run_id,
        )
        if policy.confirmed_at > batch.calculation_at:
            raise ExpirySimulationBlocked("EXPIRY_POLICY_NOT_KNOWN_AS_OF")
        target = {(item.jan, item.warehouse_id) for item in batch.projections}
        grouped: dict[tuple[str, str], list[tuple[date, str]]] = {
            pair: [] for pair in target
        }
        for bucket in self.projection_service.inventory_store.list_expiry_buckets_with_location(
            batch.inventory_snapshot_id
        ):
            pair = (bucket["jan"], bucket["location_id"])
            if pair not in target or bucket["location_type"] != "WAREHOUSE":
                raise ExpirySimulationBlocked("SNAPSHOT_OUTSIDE_PILOT_SCOPE")
            if bucket["bucket_kind"] != "EXPIRY_BUCKET":
                raise ExpirySimulationBlocked("UNSUPPORTED_BUCKET_KIND")
            if bucket["normalized_unit"] != "CASE":
                raise ExpirySimulationBlocked("INVENTORY_UNIT_MISMATCH")
            raw_date = bucket["expiry_date"]
            if raw_date is None:
                raise ExpirySimulationBlocked("EXPIRY_DATE_MISSING")
            try:
                expiry_date = (
                    raw_date if isinstance(raw_date, date) and not isinstance(raw_date, datetime)
                    else date.fromisoformat(str(raw_date))
                )
            except ValueError as exc:
                raise ExpirySimulationBlocked("EXPIRY_DATE_INVALID") from exc
            grouped[pair].append((expiry_date, bucket["quantity_cases"]))
        simulations = []
        for projection in batch.projections:
            try:
                simulations.append(simulate_expiry(
                    projection, tuple(grouped[(projection.jan, projection.warehouse_id)]), policy,
                ))
            except ValueError as exc:
                raise ExpirySimulationBlocked("EXPIRY_SIMULATION_INPUT_INVALID") from exc
        return ExpirySimulationBatch(
            batch.inventory_snapshot_id, pilot_scope_version, identity_bridge_version,
            forecast_run_id, policy, batch.calculation_at, batch.snapshot_at,
            batch.snapshot_known_at, batch.forecast_cutoff_at,
            batch.forecast_finished_at, tuple(simulations),
        )
