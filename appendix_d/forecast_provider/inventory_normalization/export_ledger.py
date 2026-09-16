"""在庫特徴CSVの内容アドレス発行台帳。"""

from datetime import UTC, datetime

from .export import feature_view_csv


class InventoryFeatureExportMixin:
    def publish_feature_export(self, mapping_version, as_of, published_by):
        if not published_by:
            raise ValueError("発行者は必須です")
        view = self.feature_view(mapping_version, as_of, 2_147_483_647, 0)
        _content, checksum = feature_view_csv(view)
        export_id = f"inventory-feature-{checksum}"
        record = {
            "export_id": export_id,
            "view_id": view["view_id"],
            "mapping_version": view["mapping_version"],
            "as_of": view["as_of"],
            "content_sha256": checksum,
            "row_count": view["total"],
            "published_by": published_by,
            "published_at": datetime.now(UTC).isoformat(),
        }
        with self._connect() as db:
            db.execute(
                "INSERT INTO inventory_feature_exports VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                tuple(record.values()),
            )
            row = db.execute(
                "SELECT * FROM inventory_feature_exports WHERE export_id=?", (export_id,)
            ).fetchone()
        stored = dict(row)
        for key in (
            "export_id",
            "view_id",
            "mapping_version",
            "as_of",
            "content_sha256",
            "row_count",
        ):
            if stored[key] != record[key]:
                raise ValueError("同じexport IDの内容が一致しません")
        return stored

    def list_feature_exports(self):
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM inventory_feature_exports "
                    "ORDER BY published_at DESC,export_id DESC"
                )
            ]

    def feature_export_content(self, export_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM inventory_feature_exports WHERE export_id=?", (export_id,)
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        view = self.feature_view(
            record["mapping_version"], record["as_of"], 2_147_483_647, 0
        )
        content, checksum = feature_view_csv(view)
        if view["view_id"] != record["view_id"] or checksum != record["content_sha256"]:
            raise ValueError("発行済み在庫特徴CSVのchecksumが一致しません")
        return record, content
