"""既存の正規化規則でCSV sampleを無更新検査する。"""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from ..normalization.processor import normalize_row, required_columns
from .contracts import InputFailure
from .loader import SourceInput

_REASON_CODES = {
    "日付形式がmappingと一致しません": "INVALID_DATE",
    "数量が数値ではありません": "INVALID_QUANTITY",
    "数量が有限値ではありません": "NON_FINITE_QUANTITY",
    "負数量は自動補正せず隔離します": "NEGATIVE_QUANTITY",
    "JANが空です": "MISSING_JAN",
    "商品名が空です": "MISSING_PRODUCT_NAME",
    "centerが空です": "MISSING_CENTER",
    "単位が許可listにありません": "UNIT_NOT_ALLOWED",
    "返品・取消・不明行区分は出荷数量から隔離します": "NON_SHIPMENT_ROW",
    "available_atがISO datetimeではありません": "INVALID_AVAILABLE_AT",
    "available_atはtimezone付きです": "AVAILABLE_AT_WITHOUT_TIMEZONE",
}


@dataclass(frozen=True)
class Inspection:
    sampled_rows: int
    accepted_rows: int
    quarantined_rows: int
    truncated: bool
    reason_counts: dict[str, int]
    quantity_reconciled: bool


def _reason_codes(error: str | None) -> list[str]:
    if not error:
        return []
    return [_REASON_CODES.get(item, "UNCLASSIFIED") for item in error.split("; ")]


def inspect_sample(source: SourceInput, mapping: dict, sample_rows: int) -> Inspection:
    try:
        with io.TextIOWrapper(
            io.BytesIO(source.data), encoding=source.encoding, errors="strict", newline=""
        ) as stream:
            reader = csv.DictReader(stream, strict=True)
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)):
                raise InputFailure("HEADER_UNIQUE")
            if required_columns(mapping) - set(headers):
                raise InputFailure("REQUIRED_COLUMNS")
            rows = []
            truncated = False
            for number, raw in enumerate(reader, start=2):
                if len(rows) == sample_rows:
                    truncated = True
                    break
                rows.append(normalize_row("dry-run", "source", number, raw, mapping))
    except InputFailure:
        raise
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise InputFailure("CSV_STRUCTURE") from exc
    if not rows:
        raise InputFailure("SAMPLE_ROWS")
    accepted = [row for row in rows if row.status == "ACCEPTED"]
    quarantined = [row for row in rows if row.status == "QUARANTINED"]
    parseable = sum((row.quantity for row in rows if row.quantity is not None), Decimal(0))
    accepted_quantity = sum(
        (row.quantity for row in accepted if row.quantity is not None), Decimal(0)
    )
    quarantined_quantity = sum(
        (row.quantity for row in quarantined if row.quantity is not None), Decimal(0)
    )
    reasons = Counter(code for row in quarantined for code in _reason_codes(row.error))
    return Inspection(
        sampled_rows=len(rows),
        accepted_rows=len(accepted),
        quarantined_rows=len(quarantined),
        truncated=truncated,
        reason_counts=dict(sorted(reasons.items())),
        quantity_reconciled=parseable == accepted_quantity + quarantined_quantity,
    )
