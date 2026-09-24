"""location masterとroute lead time policyのdomain。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from .contracts import LocationType, RecommendationBasis


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label}は必須です")
    return normalized


def _aware_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label}はtimezone付き日時で指定してください")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class LocationMasterVersion:
    location_master_version: str
    content_sha256: str
    created_by: str
    reason: str
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "location_master_version",
            "created_by",
            "reason",
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        if len(self.content_sha256) != 64 or any(
            value not in "0123456789abcdef" for value in self.content_sha256.lower()
        ):
            raise ValueError("content_sha256は64文字のSHA-256 hexadecimalで指定してください")
        object.__setattr__(self, "content_sha256", self.content_sha256.lower())
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "created_at"))


@dataclass(frozen=True)
class InventoryLocation:
    location_master_version: str
    location_id: str
    location_code: str
    location_name: str
    location_type: LocationType
    effective_from: date
    effective_to: date | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "location_master_version",
            "location_id",
            "location_code",
            "location_name",
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        if not isinstance(self.location_type, LocationType):
            raise ValueError("location_typeはFACTORYまたはWAREHOUSEです")
        if isinstance(self.effective_from, datetime) or not isinstance(self.effective_from, date):
            raise ValueError("effective_fromはdateで指定してください")
        if self.effective_to is not None:
            if isinstance(self.effective_to, datetime) or not isinstance(self.effective_to, date):
                raise ValueError("effective_toはdateで指定してください")
            if self.effective_to < self.effective_from:
                raise ValueError("effective_toはeffective_from以降にしてください")


@dataclass(frozen=True)
class RouteLeadTimePolicy:
    policy_id: str
    policy_version: str
    location_master_version: str
    factory_location_id: str
    warehouse_location_id: str
    minimum_hours: int
    standard_hours: int
    maximum_hours: int
    recommendation_basis: RecommendationBasis
    effective_from: date
    effective_to: date | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "policy_id",
            "policy_version",
            "location_master_version",
            "factory_location_id",
            "warehouse_location_id",
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        if self.factory_location_id == self.warehouse_location_id:
            raise ValueError("factoryとwarehouseは異なるlocationを指定してください")
        values = (self.minimum_hours, self.standard_hours, self.maximum_hours)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("lead timeは整数時間で指定してください")
        if not (12 <= self.minimum_hours <= self.standard_hours <= self.maximum_hours <= 36):
            raise ValueError("V1 lead timeは12 <= minimum <= standard <= maximum <= 36です")
        if not isinstance(self.recommendation_basis, RecommendationBasis):
            raise ValueError("recommendation_basisが不正です")
        if isinstance(self.effective_from, datetime) or not isinstance(self.effective_from, date):
            raise ValueError("effective_fromはdateで指定してください")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_toはeffective_from以降にしてください")

    @property
    def selected_lead_time_hours(self) -> int:
        return {
            RecommendationBasis.MINIMUM: self.minimum_hours,
            RecommendationBasis.STANDARD: self.standard_hours,
            RecommendationBasis.MAXIMUM: self.maximum_hours,
        }[self.recommendation_basis]


def validate_route_locations(
    policy: RouteLeadTimePolicy, locations: list[InventoryLocation] | tuple[InventoryLocation, ...]
) -> None:
    by_id = {
        value.location_id: value
        for value in locations
        if value.location_master_version == policy.location_master_version
    }
    factory = by_id.get(policy.factory_location_id)
    warehouse = by_id.get(policy.warehouse_location_id)
    if factory is None or factory.location_type is not LocationType.FACTORY:
        raise ValueError("factory_location_idは同じ版のFACTORYを指定してください")
    if warehouse is None or warehouse.location_type is not LocationType.WAREHOUSE:
        raise ValueError("warehouse_location_idは同じ版のWAREHOUSEを指定してください")

