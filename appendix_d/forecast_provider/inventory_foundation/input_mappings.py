"""確認済みInventory Input Mapping CSVの決定的な正式取込。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime

from .contracts import NormalizedUnit, ProductIdentifierKind
from .mapping import InventoryInputMappingVersion

INPUT_MAPPING_HEADER = [
    "商品列",
    "商品識別種別",
    "商品mapping版",
    "拠点列",
    "location master版",
    "賞味期限列",
    "数量列",
    "snapshot日時列",
    "原本数量列名",
    "原本単位表記",
    "正規化単位",
    "文字コード",
    "区切り文字",
    "header行",
    "確認メモ",
]
CONFIRMED_NOTE = "確認済み"
MAX_INPUT_MAPPING_BYTES = 256 * 1024
DELIMITERS = {"COMMA": ",", "TAB": "\t"}
ENCODINGS = frozenset({"utf-8", "utf-8-sig", "cp932"})


@dataclass(frozen=True)
class InventoryInputMappingImport:
    mapping: InventoryInputMappingVersion
    content_sha256: str


def parse_confirmed_input_mapping_csv(
    content: bytes,
    *,
    created_by: str,
    reason: str,
    created_at: datetime,
) -> InventoryInputMappingImport:
    """人手確認済みの1行だけを正式な入力mappingへ変換する。"""

    if not content or len(content) > MAX_INPUT_MAPPING_BYTES:
        raise ValueError("input mappingは1 byte以上256 KiB以下にしてください")
    try:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames != INPUT_MAPPING_HEADER:
            raise ValueError("input mappingの列がtemplateと一致しません")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("input mappingはUTF-8 CSVで保存してください") from exc
    if len(rows) != 1:
        raise ValueError("input mappingは1行で指定してください")

    row = rows[0]
    if (row.get("確認メモ") or "").strip() != CONFIRMED_NOTE:
        raise ValueError("確認メモを確認済みにしてください")
    try:
        identifier_kind = ProductIdentifierKind(
            (row.get("商品識別種別") or "").strip()
        )
    except ValueError as exc:
        raise ValueError("商品識別種別はJANまたはPRODUCT_CODEです") from exc
    product_mapping_version = (row.get("商品mapping版") or "").strip() or None
    normalized_unit = (row.get("正規化単位") or "").strip()
    if normalized_unit != NormalizedUnit.CASE.value:
        raise ValueError("V1の正規化単位はCASEです")
    encoding = (row.get("文字コード") or "").strip().lower()
    if encoding not in ENCODINGS:
        raise ValueError("文字コードはutf-8、utf-8-sig、cp932のいずれかです")
    delimiter_name = (row.get("区切り文字") or "").strip().upper()
    if delimiter_name not in DELIMITERS:
        raise ValueError("区切り文字はCOMMAまたはTABです")
    try:
        header_row = int((row.get("header行") or "").strip())
    except ValueError as exc:
        raise ValueError("header行は1以上の整数です") from exc

    payload = {
        "delimiter": DELIMITERS[delimiter_name],
        "encoding": encoding,
        "expiry_column": (row.get("賞味期限列") or "").strip(),
        "header_row": header_row,
        "location_column": (row.get("拠点列") or "").strip(),
        "location_master_version": (row.get("location master版") or "").strip(),
        "normalized_unit": normalized_unit,
        "product_column": (row.get("商品列") or "").strip(),
        "product_identifier_kind": identifier_kind.value,
        "product_mapping_version": product_mapping_version,
        "quantity_column": (row.get("数量列") or "").strip(),
        "snapshot_at_column": (row.get("snapshot日時列") or "").strip(),
        "source_quantity_column_name": (row.get("原本数量列名") or "").strip(),
        "source_unit_label": (row.get("原本単位表記") or "").strip(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    digest = hashlib.sha256(encoded).hexdigest()
    mapping = InventoryInputMappingVersion(
        f"inventory-input-map-{digest}",
        payload["product_column"],
        identifier_kind,
        product_mapping_version,
        payload["location_column"],
        payload["location_master_version"],
        payload["expiry_column"],
        payload["quantity_column"],
        payload["snapshot_at_column"],
        payload["source_quantity_column_name"],
        payload["source_unit_label"],
        NormalizedUnit.CASE,
        encoding,
        payload["delimiter"],
        header_row,
        created_by,
        reason,
        created_at,
    )
    return InventoryInputMappingImport(mapping, digest)
