"""出荷行正規化の版付き契約。"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ColumnMapping:
    mapping_id: str
    format_version: int
    content_hash: str
    definition: dict


@dataclass(frozen=True)
class SourceSelection:
    selection_id: str
    logical_path: str
    source_file_id: str
    decision_version: str
    decided_by: str
    reason: str
    decided_at: str


@dataclass(frozen=True)
class NormalizationJob:
    normalization_id: str
    source_file_id: str
    mapping_id: str
    status: str
    total_rows: int = 0
    accepted_rows: int = 0
    quarantined_rows: int = 0
    error: str | None = None


@dataclass(frozen=True)
class ShipmentRow:
    normalization_id: str
    source_file_id: str
    row_number: int
    center_id: str | None
    shipment_date: str | None
    raw_jan: str | None
    raw_product_name: str | None
    quantity: Decimal | None
    unit: str | None
    row_type: str | None
    available_at: str | None
    status: str
    error: str | None


@dataclass(frozen=True)
class Reconciliation:
    normalization_id: str
    parseable_quantity: Decimal
    accepted_quantity: Decimal
    quarantined_quantity: Decimal
    unexplained_quantity: Decimal
