"""版付き商品mapping台帳の永続化mixin。"""

from __future__ import annotations

from .domain import canonical_datetime
from .job_store import _datetime
from .product_mappings import ProductMappingVersion
from .references import ProductMappingRecord


class InventoryProductMappingStoreMixin:
    def put_product_mapping(
        self,
        version: ProductMappingVersion,
        records: tuple[ProductMappingRecord, ...] | list[ProductMappingRecord],
    ) -> None:
        if len(records) != version.row_count:
            raise ValueError("商品mappingの件数がversion metadataと一致しません")
        if any(
            record.product_mapping_version != version.product_mapping_version
            for record in records
        ):
            raise ValueError("商品mappingは同じversionで指定してください")
        codes = [record.source_product_code for record in records]
        if len(codes) != len(set(codes)):
            raise ValueError("商品コードが重複しています")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT 1 FROM inventory_product_mapping_versions "
                "WHERE product_mapping_version=?",
                (version.product_mapping_version,),
            ).fetchone()
            if existing is not None:
                stored = db.execute(
                    "SELECT source_product_code,jan,canonical_product_id "
                    "FROM inventory_product_mappings WHERE product_mapping_version=? "
                    "ORDER BY source_product_code",
                    (version.product_mapping_version,),
                ).fetchall()
                actual = tuple(
                    (row["source_product_code"], row["jan"], row["canonical_product_id"])
                    for row in stored
                )
                expected = tuple(
                    sorted(
                        (
                            record.source_product_code,
                            record.jan,
                            record.canonical_product_id,
                        )
                        for record in records
                    )
                )
                if actual == expected:
                    return
                raise ValueError("同じ商品mapping versionの内容は変更できません")
            db.execute(
                "INSERT INTO inventory_product_mapping_versions VALUES (?,?,?,?,?,?,?)",
                (
                    version.product_mapping_version,
                    version.content_sha256,
                    version.row_count,
                    version.source_reference,
                    version.created_by,
                    version.reason,
                    canonical_datetime(version.created_at),
                ),
            )
            db.executemany(
                "INSERT INTO inventory_product_mappings VALUES (?,?,?,?)",
                [
                    (
                        record.product_mapping_version,
                        record.source_product_code,
                        record.jan,
                        record.canonical_product_id,
                    )
                    for record in records
                ],
            )

    def get_product_mapping_version(
        self, product_mapping_version: str
    ) -> ProductMappingVersion | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM inventory_product_mapping_versions "
                "WHERE product_mapping_version=?",
                (product_mapping_version,),
            ).fetchone()
        if row is None:
            return None
        return ProductMappingVersion(
            row["product_mapping_version"],
            row["content_sha256"],
            row["row_count"],
            row["source_reference"],
            row["created_by"],
            row["reason"],
            _datetime(row["created_at"]),
        )

    def list_product_mappings(
        self, product_mapping_version: str
    ) -> tuple[ProductMappingRecord, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM inventory_product_mappings "
                "WHERE product_mapping_version=? ORDER BY source_product_code",
                (product_mapping_version,),
            ).fetchall()
        return tuple(
            ProductMappingRecord(
                row["product_mapping_version"],
                row["source_product_code"],
                row["jan"],
                row["canonical_product_id"],
            )
            for row in rows
        )
