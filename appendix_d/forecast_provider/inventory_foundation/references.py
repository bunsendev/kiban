"""CSV validationで利用する版付き商品・location参照。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .contracts import LocationType, ProductIdentifierKind, QuarantineReason
from .domain import validate_jan
from .locations import InventoryLocation
from .mapping import InventoryInputMappingVersion


@dataclass(frozen=True)
class ProductMappingRecord:
    product_mapping_version: str
    source_product_code: str
    jan: str
    canonical_product_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "product_mapping_version",
            "source_product_code",
            "canonical_product_id",
        ):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name}は必須です")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "jan", validate_jan(self.jan))


@dataclass(frozen=True)
class ResolvedProduct:
    jan: str
    canonical_product_id: str | None


class InventoryReferenceResolver:
    """参照versionを跨がず、CSV値をcanonical IDへ解決する。"""

    def __init__(
        self,
        mapping: InventoryInputMappingVersion,
        locations: tuple[InventoryLocation, ...] | list[InventoryLocation],
        product_mappings: tuple[ProductMappingRecord, ...] | list[ProductMappingRecord] = (),
        jan_canonical_ids: dict[str, str] | None = None,
    ) -> None:
        self.mapping = mapping
        self._locations: dict[str, list[InventoryLocation]] = defaultdict(list)
        for location in locations:
            if location.location_master_version == mapping.location_master_version:
                self._locations[location.location_code].append(location)
        self._products: dict[str, list[ProductMappingRecord]] = defaultdict(list)
        for product in product_mappings:
            if product.product_mapping_version == mapping.product_mapping_version:
                self._products[product.source_product_code].append(product)
        self._jan_canonical_ids = dict(jan_canonical_ids or {})

    def resolve_product(
        self, source_value: str
    ) -> tuple[ResolvedProduct | None, QuarantineReason | None]:
        value = source_value.strip()
        if self.mapping.product_identifier_kind is ProductIdentifierKind.JAN:
            if not value:
                return None, QuarantineReason.JAN_MISSING
            try:
                jan = validate_jan(value)
            except ValueError:
                return None, QuarantineReason.JAN_INVALID
            return ResolvedProduct(jan, self._jan_canonical_ids.get(jan)), None

        if not value:
            return None, QuarantineReason.PRODUCT_MAPPING_MISSING
        matches = self._products.get(value, [])
        if not matches:
            return None, QuarantineReason.PRODUCT_MAPPING_MISSING
        identities = {(item.jan, item.canonical_product_id) for item in matches}
        if len(identities) != 1:
            return None, QuarantineReason.PRODUCT_MAPPING_AMBIGUOUS
        jan, canonical_product_id = next(iter(identities))
        return ResolvedProduct(jan, canonical_product_id), None

    def resolve_location(
        self, source_value: str, snapshot_date: date | None
    ) -> tuple[InventoryLocation | None, QuarantineReason | None]:
        value = source_value.strip()
        if not value:
            return None, QuarantineReason.LOCATION_MISSING
        matches = self._locations.get(value, [])
        if snapshot_date is not None:
            matches = [
                item
                for item in matches
                if item.effective_from <= snapshot_date
                and (item.effective_to is None or snapshot_date <= item.effective_to)
            ]
        if not matches:
            return None, QuarantineReason.LOCATION_UNKNOWN
        identities = {(item.location_id, item.location_type) for item in matches}
        if len(identities) != 1:
            return None, QuarantineReason.LOCATION_AMBIGUOUS
        location = matches[0]
        if location.location_type not in {LocationType.FACTORY, LocationType.WAREHOUSE}:
            return None, QuarantineReason.LOCATION_TYPE_INVALID
        return location, None
