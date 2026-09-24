"""版付きmappingに従ってCSVを安全な行境界へ変換する。"""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import json
from dataclasses import dataclass, field

from .contracts import InventoryCsvErrorCode
from .mapping import InventoryInputMappingVersion

_ALLOWED_ENCODINGS = frozenset({"utf-8", "utf-8-sig", "cp932"})


class InventoryCsvContractError(ValueError):
    """業務値を含めず、固定codeだけを外部へ返すCSV契約エラー。"""

    def __init__(self, code: InventoryCsvErrorCode):
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True)
class ParsedInventoryCsvRow:
    row_number: int
    row_sha256: str
    values: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    shape_valid: bool = True

    def as_dict(self) -> dict[str, str]:
        return dict(self.values)


@dataclass(frozen=True)
class ParsedInventoryCsv:
    source_sha256: str
    mapping_version: str
    headers: tuple[str, ...]
    rows: tuple[ParsedInventoryCsvRow, ...]


def _encoding_name(value: str) -> str:
    try:
        name = codecs.lookup(value).name
    except LookupError as exc:
        raise InventoryCsvContractError(InventoryCsvErrorCode.ENCODING_UNSUPPORTED) from exc
    aliases = {"utf-8": "utf-8", "utf-8-sig": "utf-8-sig", "cp932": "cp932"}
    if name not in aliases:
        raise InventoryCsvContractError(InventoryCsvErrorCode.ENCODING_UNSUPPORTED)
    return aliases[name]


def _row_hash(row: list[str]) -> str:
    payload = json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_inventory_csv(
    content: bytes,
    mapping: InventoryInputMappingVersion,
) -> ParsedInventoryCsv:
    """CSVをdecodeし、raw値を公開結果へ複写しない行objectを返す。"""

    if not content:
        raise InventoryCsvContractError(InventoryCsvErrorCode.EMPTY_SOURCE)
    encoding = _encoding_name(mapping.encoding)
    try:
        text = content.decode(encoding, errors="strict")
    except UnicodeDecodeError:
        raise InventoryCsvContractError(InventoryCsvErrorCode.DECODE_FAILED) from None
    try:
        parsed = list(
            csv.reader(
                io.StringIO(text, newline=""),
                delimiter=mapping.delimiter,
                strict=True,
            )
        )
    except csv.Error:
        raise InventoryCsvContractError(InventoryCsvErrorCode.CSV_MALFORMED) from None

    header_index = mapping.header_row - 1
    if len(parsed) <= header_index:
        raise InventoryCsvContractError(InventoryCsvErrorCode.HEADER_MISSING)
    headers = tuple(value.strip() for value in parsed[header_index])
    if not headers or any(not value for value in headers):
        raise InventoryCsvContractError(InventoryCsvErrorCode.HEADER_MISSING)
    if len(headers) != len(set(headers)):
        raise InventoryCsvContractError(InventoryCsvErrorCode.HEADER_DUPLICATE)
    required = {
        mapping.product_column,
        mapping.location_column,
        mapping.expiry_column,
        mapping.quantity_column,
        mapping.snapshot_at_column,
    }
    if not required.issubset(headers):
        raise InventoryCsvContractError(InventoryCsvErrorCode.REQUIRED_COLUMN_MISSING)

    rows: list[ParsedInventoryCsvRow] = []
    for index, row in enumerate(parsed[header_index + 1 :], start=mapping.header_row + 1):
        if not row or all(not value.strip() for value in row):
            continue
        shape_valid = len(row) == len(headers)
        values = tuple(zip(headers, row, strict=True)) if shape_valid else ()
        rows.append(ParsedInventoryCsvRow(index, _row_hash(row), values, shape_valid))
    return ParsedInventoryCsv(
        hashlib.sha256(content).hexdigest(),
        mapping.mapping_version,
        headers,
        tuple(rows),
    )
