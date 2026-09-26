"""版付きInventory Input Mappingの永続化mixin。"""

from __future__ import annotations

from .contracts import NormalizedUnit, ProductIdentifierKind, SnapshotAtSourceKind
from .domain import canonical_datetime
from .job_store import _datetime
from .mapping import InventoryInputMappingVersion


class InventoryInputMappingStoreMixin:
    def put_mapping(self, value: InventoryInputMappingVersion) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT 1 FROM inventory_location_master_versions "
                    "WHERE location_master_version=?",
                    (value.location_master_version,),
                ).fetchone()
                is None
            ):
                raise ValueError("location master versionが見つかりません")
            if value.product_identifier_kind is ProductIdentifierKind.PRODUCT_CODE and (
                db.execute(
                    "SELECT 1 FROM inventory_product_mapping_versions "
                    "WHERE product_mapping_version=?",
                    (value.product_mapping_version,),
                ).fetchone()
                is None
            ):
                raise ValueError("product mapping versionが見つかりません")
            if value.snapshot_at_source_kind is SnapshotAtSourceKind.FILENAME_YYYYMMDD and (
                db.execute(
                    "SELECT 1 FROM inventory_snapshot_time_policies WHERE policy_version=?",
                    (value.snapshot_at_policy_version,),
                ).fetchone()
                is None
            ):
                raise ValueError("snapshot time policy versionが見つかりません")
            existing = db.execute(
                "SELECT * FROM inventory_input_mapping_versions WHERE mapping_version=?",
                (value.mapping_version,),
            ).fetchone()
            expected = _values(value)
            if existing is not None:
                actual = tuple(existing[key] for key in _CONTRACT_COLUMNS)
                expected_contract = tuple(
                    expected[_COLUMNS.index(key)] for key in _CONTRACT_COLUMNS
                )
                if actual == expected_contract:
                    return
                raise ValueError("同じinput mapping versionの内容は変更できません")
            db.execute(
                "INSERT INTO inventory_input_mapping_versions ("
                + ",".join(_COLUMNS)
                + ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                expected,
            )

    def get_mapping(self, mapping_version: str) -> InventoryInputMappingVersion | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM inventory_input_mapping_versions WHERE mapping_version=?",
                (mapping_version,),
            ).fetchone()
        if row is None:
            return None
        return InventoryInputMappingVersion(
            row["mapping_version"],
            row["product_column"],
            ProductIdentifierKind(row["product_identifier_kind"]),
            row["product_mapping_version"],
            row["location_column"],
            row["location_master_version"],
            row["expiry_column"],
            row["quantity_column"],
            row["snapshot_at_column"],
            row["source_quantity_column_name"],
            row["source_unit_label"],
            NormalizedUnit(row["normalized_unit"]),
            row["encoding"],
            row["delimiter"],
            row["header_row"],
            row["created_by"],
            row["reason"],
            _datetime(row["created_at"]),
            SnapshotAtSourceKind(row["snapshot_at_source_kind"]),
            row["snapshot_at_policy_version"],
        )


_COLUMNS = (
    "mapping_version",
    "product_column",
    "product_identifier_kind",
    "product_mapping_version",
    "location_column",
    "location_master_version",
    "expiry_column",
    "quantity_column",
    "snapshot_at_column",
    "source_quantity_column_name",
    "source_unit_label",
    "normalized_unit",
    "encoding",
    "delimiter",
    "header_row",
    "created_by",
    "reason",
    "created_at",
    "snapshot_at_source_kind",
    "snapshot_at_policy_version",
)
_CONTRACT_COLUMNS = _COLUMNS[:15] + _COLUMNS[18:]


def _values(value: InventoryInputMappingVersion) -> tuple:
    return (
        value.mapping_version,
        value.product_column,
        value.product_identifier_kind.value,
        value.product_mapping_version,
        value.location_column,
        value.location_master_version,
        value.expiry_column,
        value.quantity_column,
        value.snapshot_at_column,
        value.source_quantity_column_name,
        value.source_unit_label,
        value.normalized_unit.value,
        value.encoding,
        value.delimiter,
        value.header_row,
        value.created_by,
        value.reason,
        canonical_datetime(value.created_at, "created_at"),
        value.snapshot_at_source_kind.value,
        value.snapshot_at_policy_version,
    )
