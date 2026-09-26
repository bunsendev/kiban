"""location masterとroute lead time policyの永続化mixin。"""

from __future__ import annotations

from datetime import date

from .contracts import LocationType
from .domain import canonical_datetime
from .job_store import _datetime
from .locations import (
    InventoryLocation,
    LocationMasterVersion,
    RouteLeadTimePolicy,
    validate_route_locations,
)


class InventoryLocationStoreMixin:
    def put_location_master(
        self,
        version: LocationMasterVersion,
        locations: list[InventoryLocation] | tuple[InventoryLocation, ...],
    ) -> None:
        if not locations:
            raise ValueError("locationは1件以上指定してください")
        if any(
            value.location_master_version != version.location_master_version
            for value in locations
        ):
            raise ValueError("locationは同じlocation master versionで指定してください")
        ids = [value.location_id for value in locations]
        codes = [value.location_code for value in locations]
        if len(ids) != len(set(ids)) or len(codes) != len(set(codes)):
            raise ValueError("location IDまたはcodeが重複しています")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT 1 FROM inventory_location_master_versions "
                "WHERE location_master_version=?",
                (version.location_master_version,),
            ).fetchone()
            if existing is not None:
                actual = tuple(
                    (
                        row["location_id"],
                        row["location_code"],
                        row["location_name"],
                        row["location_type"],
                        row["effective_from"],
                        row["effective_to"],
                    )
                    for row in db.execute(
                        "SELECT * FROM inventory_locations "
                        "WHERE location_master_version=? ORDER BY location_code",
                        (version.location_master_version,),
                    ).fetchall()
                )
                expected = tuple(
                    (
                        value.location_id,
                        value.location_code,
                        value.location_name,
                        value.location_type.value,
                        value.effective_from.isoformat(),
                        None
                        if value.effective_to is None
                        else value.effective_to.isoformat(),
                    )
                    for value in sorted(locations, key=lambda item: item.location_code)
                )
                if actual == expected:
                    return
                raise ValueError("同じlocation master versionの内容は変更できません")
            db.execute(
                "INSERT INTO inventory_location_master_versions VALUES (?,?,?,?,?)",
                (
                    version.location_master_version,
                    version.content_sha256,
                    version.created_by,
                    version.reason,
                    canonical_datetime(version.created_at, "created_at"),
                ),
            )
            db.executemany(
                "INSERT INTO inventory_locations VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        value.location_master_version,
                        value.location_id,
                        value.location_code,
                        value.location_name,
                        value.location_type.value,
                        value.effective_from.isoformat(),
                        None
                        if value.effective_to is None
                        else value.effective_to.isoformat(),
                    )
                    for value in locations
                ],
            )

    def get_location_master_version(
        self, location_master_version: str
    ) -> LocationMasterVersion | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM inventory_location_master_versions "
                "WHERE location_master_version=?",
                (location_master_version,),
            ).fetchone()
        if row is None:
            return None
        return LocationMasterVersion(
            row["location_master_version"],
            row["content_sha256"],
            row["created_by"],
            row["reason"],
            _datetime(row["created_at"]),
        )

    def list_locations(self, location_master_version: str) -> tuple[InventoryLocation, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM inventory_locations WHERE location_master_version=? "
                "ORDER BY location_id",
                (location_master_version,),
            ).fetchall()
        return tuple(
            InventoryLocation(
                row["location_master_version"],
                row["location_id"],
                row["location_code"],
                row["location_name"],
                LocationType(row["location_type"]),
                _date(row["effective_from"]),
                None if row["effective_to"] is None else _date(row["effective_to"]),
            )
            for row in rows
        )

    def put_route_policy(self, value: RouteLeadTimePolicy) -> None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM inventory_locations WHERE location_master_version=? "
                "AND location_id IN (?,?)",
                (
                    value.location_master_version,
                    value.factory_location_id,
                    value.warehouse_location_id,
                ),
            ).fetchall()
            locations = tuple(
                InventoryLocation(
                    row["location_master_version"],
                    row["location_id"],
                    row["location_code"],
                    row["location_name"],
                    LocationType(row["location_type"]),
                    _date(row["effective_from"]),
                    None if row["effective_to"] is None else _date(row["effective_to"]),
                )
                for row in rows
            )
            validate_route_locations(value, locations)
            db.execute(
                "INSERT INTO inventory_route_lead_time_policies VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    value.policy_id,
                    value.policy_version,
                    value.location_master_version,
                    value.factory_location_id,
                    value.warehouse_location_id,
                    value.minimum_hours,
                    value.standard_hours,
                    value.maximum_hours,
                    value.recommendation_basis.value,
                    value.effective_from.isoformat(),
                    None if value.effective_to is None else value.effective_to.isoformat(),
                ),
            )


def _date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)
