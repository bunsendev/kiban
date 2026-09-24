"""在庫snapshotの検証、Decimal正規化、決定的identity。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from .contracts import (
    BucketKind,
    InventoryIssueCode,
    NormalizedUnit,
    PdfApprovalReference,
    SnapshotIdentity,
    SourceKind,
)


def canonical_decimal(value: Decimal | int | str) -> str:
    """同値のDecimalをhash・DB共通の非指数表現へ揃える。"""

    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("在庫数量にbinary floatは使用できません")
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("数量をDecimalとして解釈できません") from exc
    if not decimal_value.is_finite():
        raise ValueError("数量は有限値で指定してください")
    if decimal_value == 0:
        return "0"
    rendered = format(decimal_value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def canonical_datetime(value: datetime, label: str = "datetime") -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label}はtimezone付き日時で指定してください")
    normalized = value.astimezone(UTC)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_jan(value: str) -> str:
    jan = value.strip()
    if len(jan) not in {8, 13} or not jan.isascii() or not jan.isdigit():
        raise ValueError("JANは8桁または13桁の数字で指定してください")
    body = jan[:-1]
    weighted = 0
    for index, digit in enumerate(reversed(body)):
        weighted += int(digit) * (3 if index % 2 == 0 else 1)
    expected = (10 - weighted % 10) % 10
    if int(jan[-1]) != expected:
        raise ValueError("JAN check digitが不正です")
    return jan


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label}は必須です")
    return normalized


def _sha(value: str, label: str) -> str:
    normalized = value.lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{label}は64文字のSHA-256 hexadecimalで指定してください")
    return normalized


@dataclass(frozen=True)
class InventoryExpiryBucket:
    jan: str
    canonical_product_id: str | None
    location_id: str
    expiry_date: date
    quantity_cases: Decimal
    bucket_kind: BucketKind = BucketKind.EXPIRY_BUCKET
    normalized_unit: NormalizedUnit = NormalizedUnit.CASE
    issue_codes: tuple[InventoryIssueCode, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "jan", validate_jan(self.jan))
        if self.canonical_product_id is not None:
            object.__setattr__(
                self,
                "canonical_product_id",
                _required(self.canonical_product_id, "canonical_product_id"),
            )
        object.__setattr__(self, "location_id", _required(self.location_id, "location_id"))
        if isinstance(self.expiry_date, datetime) or not isinstance(self.expiry_date, date):
            raise ValueError("expiry_dateはdateで指定してください")
        if isinstance(self.quantity_cases, bool) or isinstance(self.quantity_cases, float):
            raise ValueError("在庫数量にbinary floatは使用できません")
        try:
            quantity = Decimal(self.quantity_cases)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("quantity_casesが不正です") from exc
        if not quantity.is_finite() or quantity < 0:
            raise ValueError("quantity_casesは0以上の有限Decimalです")
        object.__setattr__(self, "quantity_cases", quantity)
        if self.bucket_kind is not BucketKind.EXPIRY_BUCKET:
            raise ValueError("V1 bucket_kindはEXPIRY_BUCKETです")
        if self.normalized_unit is not NormalizedUnit.CASE:
            raise ValueError("V1 normalized_unitはCASEです")
        if any(not isinstance(value, InventoryIssueCode) for value in self.issue_codes):
            raise ValueError("issue codeが不正です")
        normalized_issues = tuple(sorted(set(self.issue_codes), key=lambda value: value.value))
        object.__setattr__(self, "issue_codes", normalized_issues)


@dataclass(frozen=True)
class InventorySnapshotHeader:
    snapshot_id: str
    snapshot_at: datetime
    known_at: datetime
    source_kind: SourceKind
    source_reference: str
    source_sha256: str
    mapping_version: str
    location_master_version: str
    product_mapping_version: str
    normalized_unit: NormalizedUnit
    row_count: int
    quantity_cases_total: Decimal
    content_sha256: str
    created_at: datetime
    pdf_approval: PdfApprovalReference | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "snapshot_id",
            "source_reference",
            "mapping_version",
            "location_master_version",
            "product_mapping_version",
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        canonical_datetime(self.snapshot_at, "snapshot_at")
        canonical_datetime(self.known_at, "known_at")
        canonical_datetime(self.created_at, "created_at")
        object.__setattr__(self, "snapshot_at", self.snapshot_at.astimezone(UTC))
        object.__setattr__(self, "known_at", self.known_at.astimezone(UTC))
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
        if not isinstance(self.source_kind, SourceKind):
            raise ValueError("source_kindが不正です")
        object.__setattr__(self, "source_sha256", _sha(self.source_sha256, "source_sha256"))
        object.__setattr__(self, "content_sha256", _sha(self.content_sha256, "content_sha256"))
        if self.normalized_unit is not NormalizedUnit.CASE:
            raise ValueError("V1 normalized_unitはCASEです")
        if isinstance(self.row_count, bool) or self.row_count < 0:
            raise ValueError("row_countは0以上です")
        if isinstance(self.quantity_cases_total, bool) or isinstance(
            self.quantity_cases_total, float
        ):
            raise ValueError("在庫数量にbinary floatは使用できません")
        total = Decimal(self.quantity_cases_total)
        if not total.is_finite() or total < 0:
            raise ValueError("quantity_cases_totalは0以上の有限Decimalです")
        object.__setattr__(self, "quantity_cases_total", total)
        if self.source_kind is SourceKind.PDF_EXTRACTED and self.pdf_approval is None:
            raise ValueError("PDF_EXTRACTEDには承認済みextractionが必要です")
        if (
            self.source_kind is SourceKind.PDF_EXTRACTED
            and self.source_reference != self.pdf_approval.extraction_id
        ):
            raise ValueError("PDF source referenceは承認済みextraction IDと一致させてください")
        if self.source_kind is SourceKind.CSV and self.pdf_approval is not None:
            raise ValueError("CSVにPDF approvalは指定しません")


@dataclass(frozen=True)
class InventorySnapshot:
    header: InventorySnapshotHeader
    buckets: tuple[InventoryExpiryBucket, ...]


def _bucket_with_issues(
    value: InventoryExpiryBucket, snapshot_at: datetime
) -> InventoryExpiryBucket:
    issues = set(value.issue_codes)
    if value.expiry_date < snapshot_at.astimezone(UTC).date():
        issues.add(InventoryIssueCode.EXPIRED_AT_SNAPSHOT)
    return replace(value, issue_codes=tuple(issues))


def _bucket_payload(value: InventoryExpiryBucket) -> dict:
    return {
        "jan": value.jan,
        "canonical_product_id": value.canonical_product_id,
        "location_id": value.location_id,
        "expiry_date": value.expiry_date.isoformat(),
        "bucket_kind": value.bucket_kind.value,
        "quantity_cases": canonical_decimal(value.quantity_cases),
        "normalized_unit": value.normalized_unit.value,
        "issue_codes": [code.value for code in value.issue_codes],
    }


def build_inventory_snapshot(
    *,
    snapshot_at: datetime,
    known_at: datetime,
    source_kind: SourceKind,
    source_reference: str,
    source_sha256: str,
    mapping_version: str,
    location_master_version: str,
    product_mapping_version: str,
    buckets: list[InventoryExpiryBucket] | tuple[InventoryExpiryBucket, ...],
    created_at: datetime,
    pdf_approval: PdfApprovalReference | None = None,
) -> InventorySnapshot:
    snapshot_at_text = canonical_datetime(snapshot_at, "snapshot_at")
    known_at_text = canonical_datetime(known_at, "known_at")
    canonical_datetime(created_at, "created_at")
    if not isinstance(source_kind, SourceKind):
        raise ValueError("source_kindが不正です")
    source_reference = _required(source_reference, "source_reference")
    source_sha256 = _sha(source_sha256, "source_sha256")
    mapping_version = _required(mapping_version, "mapping_version")
    location_master_version = _required(location_master_version, "location_master_version")
    product_mapping_version = _required(product_mapping_version, "product_mapping_version")
    if source_kind is SourceKind.PDF_EXTRACTED and pdf_approval is None:
        raise ValueError("未承認PDF extractionから正式snapshotは作成できません")
    if source_kind is SourceKind.CSV and pdf_approval is not None:
        raise ValueError("CSV snapshotにPDF approvalは指定しません")

    prepared = tuple(_bucket_with_issues(value, snapshot_at) for value in buckets)
    keys = [
        (
            value.jan,
            value.location_id,
            value.expiry_date.isoformat(),
            value.normalized_unit.value,
        )
        for value in prepared
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("同じsnapshot bucket keyが重複しています")
    prepared = tuple(
        sorted(
            prepared,
            key=lambda value: (
                value.jan,
                value.location_id,
                value.expiry_date,
                value.normalized_unit.value,
            ),
        )
    )
    total = sum((value.quantity_cases for value in prepared), Decimal("0"))
    payload = {
        "format_version": "inventory-snapshot-v1",
        "source_sha256": source_sha256,
        "source_kind": source_kind.value,
        "source_reference": source_reference,
        "mapping_version": mapping_version,
        "location_master_version": location_master_version,
        "product_mapping_version": product_mapping_version,
        "snapshot_at": snapshot_at_text,
        "known_at": known_at_text,
        "normalized_unit": NormalizedUnit.CASE.value,
        "pdf_approval": None
        if pdf_approval is None
        else {
            "extraction_id": pdf_approval.extraction_id,
            "review_id": pdf_approval.review_id,
            "decision": pdf_approval.decision.value,
        },
        "buckets": [_bucket_payload(value) for value in prepared],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    content_sha256 = hashlib.sha256(encoded).hexdigest()
    identity = SnapshotIdentity(f"inventory-snapshot-{content_sha256}", content_sha256)
    header = InventorySnapshotHeader(
        snapshot_id=identity.snapshot_id,
        snapshot_at=snapshot_at,
        known_at=known_at,
        source_kind=source_kind,
        source_reference=source_reference,
        source_sha256=source_sha256,
        mapping_version=mapping_version,
        location_master_version=location_master_version,
        product_mapping_version=product_mapping_version,
        normalized_unit=NormalizedUnit.CASE,
        row_count=len(prepared),
        quantity_cases_total=total,
        content_sha256=identity.content_sha256,
        created_at=created_at,
        pdf_approval=pdf_approval,
    )
    return InventorySnapshot(header, prepared)


def verify_snapshot_identity(value: InventorySnapshot) -> None:
    rebuilt = build_inventory_snapshot(
        snapshot_at=value.header.snapshot_at,
        known_at=value.header.known_at,
        source_kind=value.header.source_kind,
        source_reference=value.header.source_reference,
        source_sha256=value.header.source_sha256,
        mapping_version=value.header.mapping_version,
        location_master_version=value.header.location_master_version,
        product_mapping_version=value.header.product_mapping_version,
        buckets=value.buckets,
        created_at=value.header.created_at,
        pdf_approval=value.header.pdf_approval,
    )
    if (
        rebuilt.header.snapshot_id != value.header.snapshot_id
        or rebuilt.header.content_sha256 != value.header.content_sha256
        or rebuilt.header.row_count != value.header.row_count
        or canonical_decimal(rebuilt.header.quantity_cases_total)
        != canonical_decimal(value.header.quantity_cases_total)
    ):
        raise ValueError("inventory snapshot identityが入力内容と一致しません")
