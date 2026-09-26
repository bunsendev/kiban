"""確認済み商品コード→JAN対応表の版管理と正式取込。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from .domain import canonical_datetime, validate_jan
from .references import ProductMappingRecord

PRODUCT_MAPPING_HEADER = ["商品コード", "商品名", "JAN", "確認メモ"]
CONFIRMED_NOTE = "確認済み"
MAX_PRODUCT_MAPPING_BYTES = 5 * 1024 * 1024
MAX_PRODUCT_MAPPING_ROWS = 10_000


@dataclass(frozen=True)
class ProductMappingVersion:
    product_mapping_version: str
    content_sha256: str
    row_count: int
    source_reference: str
    created_by: str
    reason: str
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "product_mapping_version",
            "source_reference",
            "created_by",
            "reason",
        ):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name}は必須です")
            object.__setattr__(self, field_name, value)
        digest = self.content_sha256.lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("content_sha256は64桁の16進数です")
        object.__setattr__(self, "content_sha256", digest)
        if self.row_count < 1:
            raise ValueError("row_countは1以上です")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_atはtimezone付き日時です")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


@dataclass(frozen=True)
class ProductMappingImport:
    version: ProductMappingVersion
    records: tuple[ProductMappingRecord, ...]


def parse_confirmed_product_mapping_csv(
    content: bytes,
    *,
    source_reference: str,
    created_by: str,
    reason: str,
    created_at: datetime,
    jan_canonical_ids: dict[str, str] | None = None,
) -> ProductMappingImport:
    """全行が人手確認済みのCSVだけを決定的な正式mappingへ変換する。"""

    if not content or len(content) > MAX_PRODUCT_MAPPING_BYTES:
        raise ValueError("JAN対応表は1 byte以上5 MiB以下にしてください")
    try:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames != PRODUCT_MAPPING_HEADER:
            raise ValueError("JAN対応表の列がtemplateと一致しません")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("JAN対応表はUTF-8 CSVで保存してください") from exc
    if not rows or len(rows) > MAX_PRODUCT_MAPPING_ROWS:
        raise ValueError("JAN対応表の行数が不正です")

    canonical_ids = dict(jan_canonical_ids or {})
    normalized: list[tuple[str, str, str | None]] = []
    seen_codes: set[str] = set()
    for row in rows:
        code = (row.get("商品コード") or "").strip()
        jan = (row.get("JAN") or "").strip()
        note = (row.get("確認メモ") or "").strip()
        if not code or not jan:
            raise ValueError("商品コードとJANは全行で必須です")
        if note != CONFIRMED_NOTE:
            raise ValueError("全行の確認メモを確認済みにしてください")
        if code in seen_codes:
            raise ValueError("商品コードが重複しています")
        seen_codes.add(code)
        normalized.append((code, validate_jan(jan), canonical_ids.get(jan)))

    payload = [
        {
            "canonical_product_id": canonical_product_id,
            "jan": jan,
            "source_product_code": code,
        }
        for code, jan, canonical_product_id in sorted(normalized)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    digest = hashlib.sha256(encoded).hexdigest()
    product_mapping_version = f"inventory-product-map-{digest}"
    version = ProductMappingVersion(
        product_mapping_version,
        digest,
        len(payload),
        source_reference,
        created_by,
        reason,
        created_at,
    )
    records = tuple(
        ProductMappingRecord(
            product_mapping_version,
            item["source_product_code"],
            item["jan"],
            item["canonical_product_id"],
        )
        for item in payload
    )
    return ProductMappingImport(version, records)


def serialize_product_mapping_version(value: ProductMappingVersion) -> dict:
    return {
        "product_mapping_version": value.product_mapping_version,
        "content_sha256": value.content_sha256,
        "row_count": value.row_count,
        "source_reference": value.source_reference,
        "created_by": value.created_by,
        "reason": value.reason,
        "created_at": canonical_datetime(value.created_at),
    }
