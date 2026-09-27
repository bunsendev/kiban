"""承認済みPilot在庫・確定予測runを時点条件付きで純粋計算へ接続する。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..daily.domain import series_id
from ..inventory_forecast_bridge.domain import IdentityResolutionError, resolve_identity
from ..inventory_foundation.domain import canonical_datetime, canonical_decimal
from .domain import HORIZON_DAYS, WarehouseProjection, build_warehouse_projection

JST = ZoneInfo("Asia/Tokyo")


class ProjectionBlocked(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class WarehouseProjectionBatch:
    inventory_snapshot_id: str
    pilot_scope_version: str
    identity_bridge_version: str
    forecast_run_id: str
    calculation_at: datetime
    snapshot_at: datetime
    snapshot_known_at: datetime
    forecast_cutoff_at: datetime
    forecast_finished_at: datetime
    projections: tuple[WarehouseProjection, ...]


def _date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _datetime(value) -> datetime:
    result = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    canonical_datetime(result)
    return result.astimezone(UTC)


class WarehouseProjectionService:
    def __init__(self, inventory_store, pilot_store, bridge_store, run_store):
        self.inventory_store = inventory_store
        self.pilot_store = pilot_store
        self.bridge_store = bridge_store
        self.run_store = run_store

    def calculate(
        self,
        *,
        calculation_at: datetime,
        pilot_scope_version: str,
        identity_bridge_version: str,
        forecast_run_id: str,
    ) -> WarehouseProjectionBatch:
        canonical_datetime(calculation_at, "calculation_at")
        calculation_at = calculation_at.astimezone(UTC)
        scope = self.pilot_store.get(pilot_scope_version)
        if scope is None or scope.version.created_at > calculation_at:
            raise ProjectionBlocked("PILOT_SCOPE_NOT_KNOWN_AS_OF")
        snapshot = self.inventory_store.find_approved_snapshot_as_of(
            calculation_at, pilot_scope_version=pilot_scope_version
        )
        if snapshot is None:
            raise ProjectionBlocked("APPROVED_PILOT_SNAPSHOT_NOT_FOUND")
        snapshot_id = snapshot["snapshot_id"]
        scoped_id = self.pilot_store.get_scoped_snapshot_id(snapshot_id, pilot_scope_version)
        scoped = None if scoped_id is None else self.pilot_store.get_scoped_snapshot(scoped_id)
        if scoped is None or not scoped.reconciliation.approval_ready:
            raise ProjectionBlocked("PILOT_RECONCILIATION_MISSING")
        snapshot_at = _datetime(snapshot["snapshot_at"])
        snapshot_date = snapshot_at.astimezone(JST).date()
        if not scope.is_effective(snapshot_at.date()):
            raise ProjectionBlocked("PILOT_SCOPE_NOT_EFFECTIVE")
        bridge = self.bridge_store.get(identity_bridge_version)
        if bridge is None or bridge.version.created_at > calculation_at:
            raise ProjectionBlocked("IDENTITY_BRIDGE_NOT_KNOWN_AS_OF")
        run = self.run_store.get_run(forecast_run_id)
        finished_at = self.run_store.get_run_finished_at(forecast_run_id)
        if (
            run is None or run.status != "SUCCEEDED" or finished_at is None
            or _datetime(finished_at) > calculation_at
        ):
            raise ProjectionBlocked("FORECAST_RUN_NOT_AVAILABLE_AS_OF")
        origin = self.run_store.get_origin_status(forecast_run_id, snapshot_date)
        if (
            origin is None or origin["status"] != "SUCCEEDED"
            or _datetime(origin["cutoff_at"]) > calculation_at
        ):
            raise ProjectionBlocked("FORECAST_ORIGIN_NOT_AVAILABLE_AS_OF")
        target_pairs = {(item.jan, item.warehouse_id) for item in scope.items}
        stock = {pair: Decimal("0") for pair in target_pairs}
        seen = set()
        canonical_ids = {}
        for bucket in self.inventory_store.list_expiry_buckets_with_location(snapshot_id):
            pair = (bucket["jan"], bucket["location_id"])
            if pair not in target_pairs or bucket["location_type"] != "WAREHOUSE":
                raise ProjectionBlocked("SNAPSHOT_OUTSIDE_PILOT_SCOPE")
            if _date(bucket["expiry_date"]) < snapshot_date:
                raise ProjectionBlocked("EXPIRED_STOCK_AT_SNAPSHOT")
            if bucket["normalized_unit"] != "CASE":
                raise ProjectionBlocked("INVENTORY_UNIT_MISMATCH")
            quantity = Decimal(canonical_decimal(bucket["quantity_cases"]))
            if quantity < 0:
                raise ProjectionBlocked("INVENTORY_QUANTITY_INVALID")
            stock[pair] += quantity
            seen.add(pair)
            canonical_ids.setdefault(pair, set()).add(bucket["canonical_product_id"])
        if seen != target_pairs:
            raise ProjectionBlocked("PILOT_INVENTORY_INCOMPLETE")
        start = snapshot_date + timedelta(days=1)
        identities = {}
        used_series = set()
        for jan, warehouse_id in sorted(target_pairs):
            try:
                identity = resolve_identity(
                    bridge, jan=jan, warehouse_id=warehouse_id,
                    business_date=snapshot_date, known_at=calculation_at,
                )
            except IdentityResolutionError as exc:
                raise ProjectionBlocked(exc.code) from exc
            if canonical_ids[(jan, warehouse_id)] - {None, identity.canonical_product_id}:
                raise ProjectionBlocked("INVENTORY_FORECAST_IDENTITY_MISMATCH")
            unique_id = series_id(identity.canonical_product_id, identity.forecast_center_id)
            if unique_id in used_series:
                raise ProjectionBlocked("FORECAST_SERIES_SHARED_BY_PILOT_ITEMS")
            used_series.add(unique_id)
            identities[(jan, warehouse_id)] = unique_id
        values = {}
        for value in self.run_store.list_point_values_for_origin(
            forecast_run_id, snapshot_date, tuple(sorted(used_series)),
            start, start + timedelta(days=HORIZON_DAYS - 1),
        ):
            key = (value["unique_id"], _date(value["target_date"]))
            if key in values or value["quantile"] is not None:
                raise ProjectionBlocked("FORECAST_POINT_AMBIGUOUS")
            values[key] = value["yhat"]
        projections = []
        for jan, warehouse_id in sorted(target_pairs):
            unique_id = identities[(jan, warehouse_id)]
            demands = []
            for day in range(HORIZON_DAYS):
                target = start + timedelta(days=day)
                key = (unique_id, target)
                if key not in values:
                    raise ProjectionBlocked("FORECAST_HORIZON_INCOMPLETE")
                demands.append((target, values[key]))
            projections.append(
                build_warehouse_projection(
                    jan=jan, warehouse_id=warehouse_id,
                    starting_inventory_cases=stock[(jan, warehouse_id)],
                    forecast_demand=tuple(demands), first_date=start,
                    inventory_snapshot_id=snapshot_id, pilot_scope_version=pilot_scope_version,
                    identity_bridge_version=identity_bridge_version,
                    forecast_run_id=forecast_run_id, forecast_origin_date=snapshot_date,
                    calculation_at=calculation_at,
                )
            )
        return WarehouseProjectionBatch(
            snapshot_id, pilot_scope_version, identity_bridge_version,
            forecast_run_id, calculation_at, snapshot_at, _datetime(snapshot["known_at"]),
            _datetime(origin["cutoff_at"]), _datetime(finished_at), tuple(projections),
        )
