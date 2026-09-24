"""CSV行をJAN × location × expiry × CASEへ正規化して隔離判定する。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from .contracts import QuarantineReason
from .csv_adapter import ParsedInventoryCsv, ParsedInventoryCsvRow
from .domain import InventoryExpiryBucket
from .mapping import InventoryInputMappingVersion
from .reconciliation import InventoryQuantityReconciliation
from .references import InventoryReferenceResolver, ResolvedProduct

_INTEGER_GROUPED = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_PLAIN_DECIMAL = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_EXPIRY_FORMATS = ("%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S")


@dataclass(frozen=True)
class QuarantinedInventoryRow:
    row_number: int
    row_sha256: str
    reasons: tuple[QuarantineReason, ...]


@dataclass(frozen=True)
class InventoryCsvValidationResult:
    source_sha256: str
    mapping_version: str
    snapshot_at: datetime | None
    buckets: tuple[InventoryExpiryBucket, ...]
    quarantines: tuple[QuarantinedInventoryRow, ...]
    reconciliation: InventoryQuantityReconciliation

    @property
    def approval_ready(self) -> bool:
        return bool(self.buckets) and not self.quarantines and self.reconciliation.reconciled


@dataclass
class _Candidate:
    row: ParsedInventoryCsvRow
    reasons: set[QuarantineReason] = field(default_factory=set)
    quantity: Decimal | None = None
    snapshot_at: datetime | None = None
    expiry_date: date | None = None
    product: ResolvedProduct | None = None
    location_id: str | None = None


def _parse_quantity(value: str) -> tuple[Decimal | None, QuarantineReason | None]:
    normalized = value.strip()
    if not normalized:
        return None, QuarantineReason.QUANTITY_MISSING
    if "," in normalized:
        if not _INTEGER_GROUPED.fullmatch(normalized):
            return None, QuarantineReason.QUANTITY_INVALID
        normalized = normalized.replace(",", "")
    elif not _PLAIN_DECIMAL.fullmatch(normalized):
        return None, QuarantineReason.QUANTITY_INVALID
    try:
        quantity = Decimal(normalized)
    except InvalidOperation:
        return None, QuarantineReason.QUANTITY_INVALID
    if not quantity.is_finite():
        return None, QuarantineReason.QUANTITY_INVALID
    if quantity < 0:
        return None, QuarantineReason.QUANTITY_NEGATIVE
    return quantity, None


def _parse_expiry(value: str) -> tuple[date | None, QuarantineReason | None]:
    normalized = value.strip()
    if not normalized:
        return None, QuarantineReason.EXPIRY_MISSING
    try:
        return date.fromisoformat(normalized), None
    except ValueError:
        pass
    for pattern in _EXPIRY_FORMATS:
        try:
            return datetime.strptime(normalized, pattern).date(), None
        except ValueError:
            continue
    return None, QuarantineReason.EXPIRY_INVALID


def _parse_snapshot_at(value: str) -> tuple[datetime | None, QuarantineReason | None]:
    normalized = value.strip()
    if not normalized:
        return None, QuarantineReason.SNAPSHOT_AT_MISSING
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None, QuarantineReason.SNAPSHOT_AT_INVALID
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, QuarantineReason.SNAPSHOT_AT_INVALID
    return parsed.astimezone(UTC), None


def _add_reason(candidate: _Candidate, reason: QuarantineReason | None) -> None:
    if reason is not None:
        candidate.reasons.add(reason)


def _validate_row(
    row: ParsedInventoryCsvRow,
    mapping: InventoryInputMappingVersion,
    resolver: InventoryReferenceResolver,
) -> _Candidate:
    candidate = _Candidate(row)
    if not row.shape_valid:
        candidate.reasons.add(QuarantineReason.ROW_SHAPE_INVALID)
        return candidate
    values = row.as_dict()
    candidate.quantity, reason = _parse_quantity(values[mapping.quantity_column])
    _add_reason(candidate, reason)
    candidate.expiry_date, reason = _parse_expiry(values[mapping.expiry_column])
    _add_reason(candidate, reason)
    candidate.snapshot_at, reason = _parse_snapshot_at(values[mapping.snapshot_at_column])
    _add_reason(candidate, reason)
    candidate.product, reason = resolver.resolve_product(values[mapping.product_column])
    _add_reason(candidate, reason)
    location, reason = resolver.resolve_location(
        values[mapping.location_column],
        candidate.snapshot_at.date() if candidate.snapshot_at is not None else None,
    )
    _add_reason(candidate, reason)
    if location is not None:
        candidate.location_id = location.location_id
    return candidate


def validate_inventory_csv(
    parsed: ParsedInventoryCsv,
    mapping: InventoryInputMappingVersion,
    resolver: InventoryReferenceResolver,
) -> InventoryCsvValidationResult:
    """CSVを正規化し、正式採用候補と隔離metadataを同時に返す。"""

    if parsed.mapping_version != mapping.mapping_version or resolver.mapping != mapping:
        raise ValueError("CSV解析・validation・参照解決のmapping contractが一致しません")
    candidates = [_validate_row(row, mapping, resolver) for row in parsed.rows]
    source_total = sum(
        (item.quantity for item in candidates if item.quantity is not None), Decimal("0")
    )

    seen_hashes: set[str] = set()
    for item in candidates:
        if item.row.row_sha256 in seen_hashes:
            item.reasons.add(QuarantineReason.SOURCE_DUPLICATE)
        seen_hashes.add(item.row.row_sha256)

    snapshot_values = {item.snapshot_at for item in candidates if item.snapshot_at is not None}
    snapshot_at = next(iter(snapshot_values)) if len(snapshot_values) == 1 else None
    if len(snapshot_values) > 1:
        for item in candidates:
            if item.snapshot_at is not None:
                item.reasons.add(QuarantineReason.SNAPSHOT_AT_INCONSISTENT)

    canonical_by_key: dict[tuple[str, str, date], set[str | None]] = {}
    for item in candidates:
        if item.product is None or item.location_id is None or item.expiry_date is None:
            continue
        key = (item.product.jan, item.location_id, item.expiry_date)
        canonical_by_key.setdefault(key, set()).add(item.product.canonical_product_id)
    ambiguous_keys = {key for key, values in canonical_by_key.items() if len(values) > 1}
    for item in candidates:
        if item.product is None or item.location_id is None or item.expiry_date is None:
            continue
        key = (item.product.jan, item.location_id, item.expiry_date)
        if key in ambiguous_keys:
            item.reasons.add(QuarantineReason.PRODUCT_MAPPING_AMBIGUOUS)

    aggregate: dict[tuple[str, str | None, str, date], Decimal] = {}
    accepted_rows = 0
    for item in candidates:
        if item.reasons:
            continue
        assert item.quantity is not None
        assert item.expiry_date is not None
        assert item.product is not None
        assert item.location_id is not None
        key = (
            item.product.jan,
            item.product.canonical_product_id,
            item.location_id,
            item.expiry_date,
        )
        aggregate[key] = aggregate.get(key, Decimal("0")) + item.quantity
        accepted_rows += 1

    buckets = tuple(
        InventoryExpiryBucket(jan, canonical_id, location_id, expiry_date, quantity)
        for (jan, canonical_id, location_id, expiry_date), quantity in sorted(
            aggregate.items(), key=lambda value: tuple(str(part) for part in value[0])
        )
    )
    quarantines = tuple(
        QuarantinedInventoryRow(
            item.row.row_number,
            item.row.row_sha256,
            tuple(sorted(item.reasons, key=lambda reason: reason.value)),
        )
        for item in candidates
        if item.reasons
    )
    normalized_total = sum((bucket.quantity_cases for bucket in buckets), Decimal("0"))
    reconciliation = InventoryQuantityReconciliation(
        source_total,
        normalized_total,
        len(candidates),
        accepted_rows,
        len(quarantines),
    )
    return InventoryCsvValidationResult(
        parsed.source_sha256,
        mapping.mapping_version,
        snapshot_at,
        buckets,
        quarantines,
        reconciliation,
    )
