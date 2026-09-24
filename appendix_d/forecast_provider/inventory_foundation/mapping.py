"""Phase 3S-2へ渡す版付き在庫入力mapping contract。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .contracts import NormalizedUnit, ProductIdentifierKind


@dataclass(frozen=True)
class InventoryInputMappingVersion:
    mapping_version: str
    product_column: str
    product_identifier_kind: ProductIdentifierKind
    product_mapping_version: str | None
    location_column: str
    location_master_version: str
    expiry_column: str
    quantity_column: str
    snapshot_at_column: str
    source_quantity_column_name: str
    source_unit_label: str
    normalized_unit: NormalizedUnit
    encoding: str
    delimiter: str
    header_row: int
    created_by: str
    reason: str
    created_at: datetime

    def __post_init__(self) -> None:
        required = (
            "mapping_version",
            "product_column",
            "location_column",
            "location_master_version",
            "expiry_column",
            "quantity_column",
            "snapshot_at_column",
            "source_quantity_column_name",
            "source_unit_label",
            "encoding",
            "delimiter",
            "created_by",
            "reason",
        )
        for field_name in required:
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name}は必須です")
            object.__setattr__(self, field_name, value)
        if not isinstance(self.product_identifier_kind, ProductIdentifierKind):
            raise ValueError("product_identifier_kindが不正です")
        if self.product_identifier_kind is ProductIdentifierKind.PRODUCT_CODE:
            if not self.product_mapping_version or not self.product_mapping_version.strip():
                raise ValueError("PRODUCT_CODEにはproduct mapping versionが必要です")
        elif self.product_mapping_version is not None:
            raise ValueError("JAN mappingではproduct mapping versionを指定しません")
        if self.normalized_unit is not NormalizedUnit.CASE:
            raise ValueError("V1の正規化単位はCASEです")
        if len(self.delimiter) != 1:
            raise ValueError("delimiterは1文字で指定してください")
        if isinstance(self.header_row, bool) or self.header_row < 1:
            raise ValueError("header_rowは1以上です")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_atはtimezone付き日時で指定してください")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))

