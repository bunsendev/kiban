"""採用済み在庫を時点安全にcanonical商品へ接続するread model。"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal


def _as_of(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("as_ofにはtimezoneが必要です")
    return parsed.astimezone(UTC).isoformat()


class InventoryFeatureViewMixin:
    def feature_view(self, mapping_version, as_of, limit=100, offset=0):
        cutoff = _as_of(as_of)
        with self._connect() as db:
            adoption = db.execute(
                "SELECT * FROM inventory_normalization_decisions "
                "WHERE decision='APPROVED' AND decided_at<=? "
                "ORDER BY decided_at DESC,decision_id DESC LIMIT 1",
                (cutoff,),
            ).fetchone()
            if adoption is None:
                raise ValueError("指定時点で採用済みの在庫正規化結果がありません")
            source = [
                dict(row)
                for row in db.execute(
                    "SELECT inventory_date,jan,center_id,unit,quantity "
                    "FROM inventory_daily_quantities WHERE job_id=? "
                    "ORDER BY inventory_date,jan,center_id,unit",
                    (adoption["job_id"],),
                )
            ]
            mappings = [
                dict(row)
                for row in db.execute(
                    "SELECT jan,canonical_product_id,valid_from,valid_to "
                    "FROM jan_mappings WHERE mapping_version=? "
                    "ORDER BY jan,valid_from,jan_mapping_id",
                    (mapping_version,),
                )
            ]
        by_jan = {}
        for mapping in mappings:
            by_jan.setdefault(mapping["jan"], []).append(mapping)
        resolved = []
        missing = ambiguous = 0
        total_quantity = Decimal(0)
        for value in source:
            matches = [
                item
                for item in by_jan.get(value["jan"], [])
                if item["valid_from"] <= value["inventory_date"]
                and (item["valid_to"] is None or value["inventory_date"] <= item["valid_to"])
            ]
            if not matches:
                missing += 1
                continue
            if len(matches) != 1:
                ambiguous += 1
                continue
            total_quantity += Decimal(value["quantity"])
            resolved.append(
                {
                    "canonical_product_id": matches[0]["canonical_product_id"],
                    "center_id": value["center_id"],
                    "ds": value["inventory_date"],
                    "unit": value["unit"],
                    "inventory_quantity": value["quantity"],
                    "available_at": adoption["decided_at"],
                }
            )
        payload = {
            "adoption_decision_id": adoption["decision_id"],
            "job_id": adoption["job_id"],
            "mapping_version": mapping_version,
            "as_of": cutoff,
        }
        view_id = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        ready = missing == 0 and ambiguous == 0 and bool(source)
        return {
            "view_id": view_id,
            **payload,
            "available_at": adoption["decided_at"],
            "status": "READY" if ready else "BLOCKED",
            "source_row_count": len(source),
            "resolved_row_count": len(resolved),
            "missing_mapping_count": missing,
            "ambiguous_mapping_count": ambiguous,
            "total_quantity": str(total_quantity) if ready else None,
            "total": len(resolved) if ready else 0,
            "limit": limit,
            "offset": offset,
            "items": resolved[offset : offset + limit] if ready else [],
        }
