"""未知CSVから値を保存せず、説明可能な構造候補だけを作る。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .inbox_classifier import Classification, _match, header_sha256
from .inbox_policy import InboxPolicy, SchemaRule

# 実在庫CSVの159/160列を候補化できる上限。過大なheaderは引き続き隔離する。
MAX_COLUMNS = 256
MAX_SAMPLE_ROWS = 100
ALIASES = {
    "date": ("基準日時", "基準日", "在庫日", "出荷日", "生産予定日", "date", "day"),
    "jan": ("JAN",),
    "product_code": ("商品コード", "商品CD", "product_code", "item_code"),
    "location": (
        "明細倉庫コード", "倉庫コード", "工場コード", "拠点コード",
        "倉庫", "工場", "拠点", "センター", "warehouse", "factory", "site",
    ),
    "quantity": (
        "明細バラ数", "箱数", "出荷数量", "在庫数量", "明細数量",
        "バラ数", "在庫数", "cases", "quantity", "qty", "数量",
    ),
    "expiry": ("賞味期限", "消費期限", "expiry", "expiration"),
    "product": ("商品名", "品名", "product_name"),
}
CRITICAL_TERMS = (
    "数量", "個数", "バラ", "箱", "単位", "JAN", "商品コード", "賞味期限",
    "倉庫", "工場", "拠点", "quantity", "qty", "unit", "expiry",
    "warehouse", "factory", "location",
)


@dataclass(frozen=True)
class LearningCandidate:
    header_sha256: str
    headers: tuple[str, ...]
    encoding: str
    suggested_kind: str
    confidence: str
    risk: str
    columns: dict[str, str]
    parent_schema_id: str | None
    location_id: str | None
    mapping_version: str | None
    source_unit: str | None
    normalized_unit: str | None
    sampled_rows: int
    value_types: dict[str, str]


def _value_type(values: list[str]) -> str:
    if not values or any(not value.strip() for value in values):
        return "TEXT_OR_MISSING"
    if all(_decimal(value) for value in values):
        return "NUMBER"
    if all(_date(value) for value in values):
        return "DATE"
    return "TEXT"


def _decimal(value: str) -> bool:
    try:
        return Decimal(value.strip()).is_finite()
    except InvalidOperation:
        return False


def _date(value: str) -> bool:
    try:
        date.fromisoformat(value.strip().replace("/", "-"))
        return True
    except ValueError:
        return False


def _guess(headers: tuple[str, ...], key: str) -> str | None:
    for alias in ALIASES[key]:
        for column in headers:
            if (column.casefold() == alias.casefold() if alias in {"date", "day"}
                    else alias.casefold() in column.casefold()):
                return column
    return None


def _kind(headers: tuple[str, ...]) -> tuple[str, str]:
    joined = " ".join(headers).casefold()
    if "生産" in joined and "予定" in joined:
        return "PRODUCTION_SCHEDULE", "MEDIUM"
    if ("工場" in joined or "factory" in joined) and "在庫" in joined:
        return "FACTORY_INVENTORY", "MEDIUM"
    if ("倉庫" in joined or "warehouse" in joined) and (
        "在庫" in joined or "賞味期限" in joined or "expiry" in joined
    ):
        return "WAREHOUSE_INVENTORY", "MEDIUM"
    if "出荷" in joined or "shipment" in joined:
        return "SHIPMENT_ACTUAL", "MEDIUM"
    return "OTHER", "LOW"


def _inherited_rule(
    policy: InboxPolicy, headers: tuple[str, ...], samples: list[dict],
) -> SchemaRule | None:
    matches = [
        rule for rule in policy.rules
        if set(rule.required_columns).issubset(headers)
        and _match(rule, headers, samples) is not None
    ]
    return matches[0] if len(matches) == 1 else None


def inspect_learning_candidate(
    path: Path, classification: Classification, policy: InboxPolicy,
) -> LearningCandidate | None:
    if path.suffix.lower() != ".csv" or classification.encoding is None:
        return None
    try:
        with path.open("r", encoding=classification.encoding, errors="strict", newline="") as f:
            reader = csv.DictReader(f, strict=True)
            headers = tuple(reader.fieldnames or ())
            if not headers or len(headers) > MAX_COLUMNS or len(headers) != len(set(headers)):
                return None
            if any(not name or len(name) > 120 for name in headers):
                return None
            samples = []
            for index, row in enumerate(reader):
                if index >= MAX_SAMPLE_ROWS:
                    break
                if None in row or any(value is None for value in row.values()):
                    return None
                samples.append(row)
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    if not samples:
        return None
    value_types = {
        header: _value_type([str(row[header]) for row in samples])
        for header in headers
    }
    base = _inherited_rule(policy, headers, samples)
    guessed = {key: value for key in ALIASES if (value := _guess(headers, key))}
    if base:
        guessed["date"] = base.date_column
        if base.quantity_column:
            guessed["quantity"] = base.quantity_column
        if base.location_column:
            guessed["location"] = base.location_column
        extra = set(headers) - set(base.required_columns)
        critical_extra = any(
            term.casefold() in column.casefold()
            for column in extra for term in CRITICAL_TERMS
        )
        return LearningCandidate(
            header_sha256(headers), headers, classification.encoding, base.kind,
            "HIGH", "MAJOR" if critical_extra else "LOW", guessed,
            base.schema_id, base.location_id,
            base.mapping_version, base.source_unit, base.normalized_unit,
            len(samples), value_types,
        )
    kind, confidence = _kind(headers)
    return LearningCandidate(
        header_sha256(headers), headers, classification.encoding, kind,
        confidence, "MAJOR", guessed, None, None, None,
        None, None, len(samples), value_types,
    )
