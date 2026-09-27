"""Pilot対象と原本・対象外・隔離の決定的な照合契約。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from ..inventory_foundation.domain import canonical_datetime, canonical_decimal, validate_jan
from .contracts import PilotScopeKind


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label}は必須です")
    return normalized


def _nonnegative_decimal(value: Decimal | int | str, label: str) -> Decimal:
    normalized = Decimal(canonical_decimal(value))
    if normalized < 0:
        raise ValueError(f"{label}は0以上です")
    return normalized


@dataclass(frozen=True)
class PilotScopeItem:
    pilot_scope_version: str
    jan: str
    warehouse_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pilot_scope_version", _required(self.pilot_scope_version, "pilot_scope_version")
        )
        object.__setattr__(self, "jan", validate_jan(self.jan))
        object.__setattr__(self, "warehouse_id", _required(self.warehouse_id, "warehouse_id"))


@dataclass(frozen=True)
class PilotScopeVersion:
    pilot_scope_version: str
    content_sha256: str
    scope_kind: PilotScopeKind
    effective_from: date
    effective_to: date | None
    approved_by: str
    reason: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pilot_scope_version", _required(self.pilot_scope_version, "pilot_scope_version")
        )
        if len(self.content_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.content_sha256
        ):
            raise ValueError("content_sha256は64文字のSHA-256です")
        if self.scope_kind is not PilotScopeKind.PILOT_PARTIAL:
            raise ValueError("Phase 3T-A-0のscope_kindはPILOT_PARTIALです")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_toはeffective_from以降です")
        object.__setattr__(self, "approved_by", _required(self.approved_by, "approved_by"))
        object.__setattr__(self, "reason", _required(self.reason, "reason"))
        canonical_datetime(self.created_at, "created_at")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


@dataclass(frozen=True)
class PilotScope:
    version: PilotScopeVersion
    items: tuple[PilotScopeItem, ...]

    def is_effective(self, business_date: date) -> bool:
        return self.version.effective_from <= business_date and (
            self.version.effective_to is None or business_date <= self.version.effective_to
        )

    def contains(self, jan: str, warehouse_id: str, business_date: date) -> bool:
        if not self.is_effective(business_date):
            return False
        key = (validate_jan(jan), warehouse_id.strip())
        return any((item.jan, item.warehouse_id) == key for item in self.items)


@dataclass(frozen=True)
class PilotScopeReconciliation:
    source_sha256: str
    source_row_count: int
    scoped_row_count: int
    out_of_scope_row_count: int
    quarantined_scope_row_count: int
    source_quantity_cases: Decimal
    scoped_quantity_cases: Decimal
    out_of_scope_quantity_cases: Decimal
    quarantined_scope_quantity_cases: Decimal

    @property
    def approval_ready(self) -> bool:
        return self.scoped_row_count > 0 and self.quarantined_scope_row_count == 0


@dataclass(frozen=True)
class PilotScopedSnapshotReference:
    scoped_snapshot_id: str
    inventory_snapshot_id: str
    pilot_scope_version: str
    scope_kind: PilotScopeKind
    reconciliation: PilotScopeReconciliation
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


def build_pilot_scope(
    *,
    pairs: list[tuple[str, str]] | tuple[tuple[str, str], ...],
    effective_from: date,
    effective_to: date | None,
    approved_by: str,
    reason: str,
    created_at: datetime,
) -> PilotScope:
    approved_by = _required(approved_by, "approved_by")
    reason = _required(reason, "reason")
    canonical_datetime(created_at, "created_at")
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("effective_toはeffective_from以降です")
    normalized = tuple(
        sorted(
            (validate_jan(jan), _required(warehouse, "warehouse_id")) for jan, warehouse in pairs
        )
    )
    if len(normalized) != len(set(normalized)):
        raise ValueError("Pilot ScopeのJAN×WAREHOUSEが重複しています")
    distinct_jans = {jan for jan, _warehouse in normalized}
    if not 10 <= len(distinct_jans) <= 20:
        raise ValueError("Pilot Scopeは10〜20商品のJANで作成してください")
    payload = {
        "format_version": "pilot-scope-v1",
        "scope_kind": PilotScopeKind.PILOT_PARTIAL.value,
        "effective_from": effective_from.isoformat(),
        "effective_to": None if effective_to is None else effective_to.isoformat(),
        "approved_by": approved_by,
        "reason": reason,
        "items": [{"jan": jan, "warehouse_id": warehouse} for jan, warehouse in normalized],
    }
    content_sha256 = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    version_id = f"pilot-scope-{content_sha256}"
    version = PilotScopeVersion(
        version_id,
        content_sha256,
        PilotScopeKind.PILOT_PARTIAL,
        effective_from,
        effective_to,
        approved_by,
        reason,
        created_at,
    )
    return PilotScope(version, tuple(PilotScopeItem(version_id, *pair) for pair in normalized))


def build_scope_reconciliation(
    *,
    source_sha256: str,
    source_row_count: int,
    scoped_row_count: int,
    out_of_scope_row_count: int,
    quarantined_scope_row_count: int,
    source_quantity_cases: Decimal | int | str,
    scoped_quantity_cases: Decimal | int | str,
    out_of_scope_quantity_cases: Decimal | int | str,
    quarantined_scope_quantity_cases: Decimal | int | str,
) -> PilotScopeReconciliation:
    if len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256):
        raise ValueError("source_sha256は64文字のSHA-256です")
    counts = (
        source_row_count,
        scoped_row_count,
        out_of_scope_row_count,
        quarantined_scope_row_count,
    )
    if any(isinstance(value, bool) or value < 0 for value in counts):
        raise ValueError("照合件数は0以上です")
    if source_row_count != scoped_row_count + out_of_scope_row_count + quarantined_scope_row_count:
        raise ValueError("原本行数とscope照合件数が一致しません")
    source = _nonnegative_decimal(source_quantity_cases, "source_quantity_cases")
    scoped = _nonnegative_decimal(scoped_quantity_cases, "scoped_quantity_cases")
    outside = _nonnegative_decimal(out_of_scope_quantity_cases, "out_of_scope_quantity_cases")
    quarantined = _nonnegative_decimal(
        quarantined_scope_quantity_cases, "quarantined_scope_quantity_cases"
    )
    if source != scoped + outside + quarantined:
        raise ValueError("原本数量とscope照合数量が一致しません")
    return PilotScopeReconciliation(
        source_sha256,
        source_row_count,
        scoped_row_count,
        out_of_scope_row_count,
        quarantined_scope_row_count,
        source,
        scoped,
        outside,
        quarantined,
    )


def build_scoped_snapshot_reference(
    *,
    inventory_snapshot,
    pilot_scope: PilotScope,
    reconciliation: PilotScopeReconciliation,
    recorded_at: datetime,
) -> PilotScopedSnapshotReference:
    """既存snapshotをPILOT_PARTIALとして明示し、原本照合と結び付ける。"""

    canonical_datetime(recorded_at, "recorded_at")
    header = inventory_snapshot.header
    business_date = header.snapshot_at.astimezone(UTC).date()
    if not pilot_scope.is_effective(business_date):
        raise ValueError("inventory snapshot日時はPilot Scopeの適用期間外です")
    if header.source_sha256 != reconciliation.source_sha256:
        raise ValueError("inventory snapshotとscope照合のsource SHA-256が一致しません")
    if header.quantity_cases_total != reconciliation.scoped_quantity_cases:
        raise ValueError("inventory snapshot数量とscope対象数量が一致しません")
    outside = [
        (bucket.jan, bucket.location_id)
        for bucket in inventory_snapshot.buckets
        if not pilot_scope.contains(bucket.jan, bucket.location_id, business_date)
    ]
    if outside:
        raise ValueError("inventory snapshotにPilot Scope外bucketが含まれています")
    if not reconciliation.approval_ready:
        raise ValueError("対象行の隔離があるscope照合は正式参照にできません")
    payload = {
        "format_version": "pilot-scoped-snapshot-reference-v1",
        "inventory_snapshot_id": header.snapshot_id,
        "pilot_scope_version": pilot_scope.version.pilot_scope_version,
        "scope_kind": pilot_scope.version.scope_kind.value,
        "source_sha256": reconciliation.source_sha256,
        "source_row_count": reconciliation.source_row_count,
        "scoped_row_count": reconciliation.scoped_row_count,
        "out_of_scope_row_count": reconciliation.out_of_scope_row_count,
        "quarantined_scope_row_count": reconciliation.quarantined_scope_row_count,
        "source_quantity_cases": canonical_decimal(reconciliation.source_quantity_cases),
        "scoped_quantity_cases": canonical_decimal(reconciliation.scoped_quantity_cases),
        "out_of_scope_quantity_cases": canonical_decimal(
            reconciliation.out_of_scope_quantity_cases
        ),
        "quarantined_scope_quantity_cases": canonical_decimal(
            reconciliation.quarantined_scope_quantity_cases
        ),
        "known_at": canonical_datetime(header.known_at, "known_at"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return PilotScopedSnapshotReference(
        f"pilot-scoped-snapshot-{digest}",
        header.snapshot_id,
        pilot_scope.version.pilot_scope_version,
        pilot_scope.version.scope_kind,
        reconciliation,
        header.known_at,
        recorded_at.astimezone(UTC),
        digest,
    )
