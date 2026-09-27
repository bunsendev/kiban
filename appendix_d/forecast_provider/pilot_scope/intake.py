"""原本CSV上の値からPilot対象を選ぶ、版付き・全行監査の境界。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from ..inventory_foundation.contracts import LocationType
from ..inventory_foundation.csv_adapter import ParsedInventoryCsv
from ..inventory_foundation.domain import canonical_datetime, canonical_decimal, validate_jan
from ..inventory_foundation.validation import _parse_quantity
from .domain import PilotScope

HEADER = ["原本商品値", "原本拠点コード", "JAN", "warehouse_id", "確認メモ"]
MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PilotIntakeSelector:
    intake_version: str
    source_product_value: str
    source_location_code: str
    jan: str
    warehouse_id: str


@dataclass(frozen=True)
class PilotIntakeBinding:
    intake_version: str
    content_sha256: str
    pilot_scope_version: str
    mapping_version: str
    created_by: str
    reason: str
    created_at: datetime
    selectors: tuple[PilotIntakeSelector, ...]


@dataclass(frozen=True)
class PilotSelectedRows:
    parsed: ParsedInventoryCsv
    source_row_count: int
    out_of_scope_row_count: int
    out_of_scope_quantity_cases: Decimal


class PilotIntakeError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def parse_confirmed_pilot_intake_csv(
    content: bytes,
    *,
    scope: PilotScope,
    mapping,
    resolver,
    created_by: str,
    reason: str,
    created_at: datetime,
) -> PilotIntakeBinding:
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Pilot Intake CSVは1 byte以上1 MiB以下です")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), strict=True)
        if reader.fieldnames != HEADER:
            raise ValueError("Pilot Intake CSVの列がtemplateと一致しません")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("Pilot Intake CSVはUTF-8形式で保存してください") from exc
    if not rows or len(rows) > 200:
        raise ValueError("Pilot Intake CSVの行数が不正です")
    if any(row.get("確認メモ") != "確認済み" or None in row for row in rows):
        raise ValueError("Pilot Intake CSVの全行を確認済みにしてください")
    if resolver.mapping != mapping:
        raise ValueError("Pilot Intakeのmappingとresolverが一致しません")
    canonical_datetime(created_at, "created_at")
    if not created_by.strip() or not reason.strip():
        raise ValueError("登録者と理由は必須です")
    normalized = []
    for row in rows:
        source_product = row["原本商品値"].strip()
        source_location = row["原本拠点コード"].strip()
        jan = validate_jan(row["JAN"])
        warehouse = row["warehouse_id"].strip()
        if not source_product or not source_location or not warehouse:
            raise ValueError("Pilot Intakeの原本値とwarehouse_idは必須です")
        if not scope.contains(jan, warehouse, scope.version.effective_from):
            raise ValueError("Pilot IntakeにPilot Scope外のJAN×倉庫が含まれます")
        product, product_error = resolver.resolve_product(source_product)
        if product_error is not None or product is None or product.jan != jan:
            raise ValueError("Pilot Intakeの商品値と正式mappingが一致しません")
        for boundary in (scope.version.effective_from, scope.version.effective_to):
            if boundary is None:
                continue
            location, location_error = resolver.resolve_location(source_location, boundary)
            if (
                location_error is not None
                or location is None
                or location.location_id != warehouse
                or location.location_type is not LocationType.WAREHOUSE
            ):
                raise ValueError("Pilot Intakeの拠点コードと正式locationが一致しません")
        normalized.append((source_product, source_location, jan, warehouse))
    normalized.sort()
    source_keys = [(product, location) for product, location, _jan, _warehouse in normalized]
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("Pilot Intakeの原本商品値×拠点コードが重複しています")
    targets = {(jan, warehouse) for _product, _location, jan, warehouse in normalized}
    expected = {(item.jan, item.warehouse_id) for item in scope.items}
    if targets != expected:
        raise ValueError("Pilot IntakeはPilot Scopeの全JAN×倉庫を網羅してください")
    payload = {
        "format_version": "pilot-intake-v1",
        "pilot_scope_version": scope.version.pilot_scope_version,
        "mapping_version": mapping.mapping_version,
        "created_by": created_by.strip(),
        "reason": reason.strip(),
        "selectors": normalized,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    version = f"pilot-intake-{digest}"
    return PilotIntakeBinding(
        version,
        digest,
        scope.version.pilot_scope_version,
        mapping.mapping_version,
        created_by.strip(),
        reason.strip(),
        created_at.astimezone(UTC),
        tuple(PilotIntakeSelector(version, *item) for item in normalized),
    )


def select_pilot_rows(
    parsed: ParsedInventoryCsv,
    *,
    mapping,
    binding: PilotIntakeBinding,
) -> PilotSelectedRows:
    if (
        parsed.mapping_version != binding.mapping_version
        or mapping.mapping_version != binding.mapping_version
    ):
        raise PilotIntakeError("PILOT_MAPPING_MISMATCH")
    selectors = {
        (item.source_product_value, item.source_location_code): (item.jan, item.warehouse_id)
        for item in binding.selectors
    }
    seen_targets = set()
    selected = []
    out_count = 0
    out_quantity = Decimal("0")
    for row in parsed.rows:
        if not row.shape_valid:
            selected.append(row)  # 帰属不明の異常行は承認を止める。
            continue
        values = row.as_dict()
        key = (values[mapping.product_column].strip(), values[mapping.location_column].strip())
        if key in selectors:
            selected.append(row)
            seen_targets.add(selectors[key])
            continue
        quantity, error = _parse_quantity(values[mapping.quantity_column])
        if error is not None or quantity is None:
            raise PilotIntakeError("OUT_OF_SCOPE_QUANTITY_UNRECONCILABLE")
        out_count += 1
        out_quantity += quantity
    if seen_targets != set(selectors.values()):
        raise PilotIntakeError("PILOT_SCOPE_INCOMPLETE")
    return PilotSelectedRows(
        ParsedInventoryCsv(
            parsed.source_sha256,
            parsed.mapping_version,
            parsed.headers,
            tuple(selected),
        ),
        len(parsed.rows),
        out_count,
        Decimal(canonical_decimal(out_quantity)),
    )
