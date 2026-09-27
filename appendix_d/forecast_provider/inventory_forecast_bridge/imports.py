"""確認済みJAN/locationから予測IDへの対応CSV。"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from .domain import InventoryForecastBridge, build_inventory_forecast_bridge

HEADER = [
    "JAN",
    "warehouse_id",
    "canonical_product_id",
    "forecast_center_id",
    "effective_from",
    "effective_to",
    "確認メモ",
]
MAX_BYTES = 1024 * 1024


def parse_confirmed_inventory_forecast_bridge_csv(
    content: bytes,
    *,
    created_by: str,
    reason: str,
    created_at: datetime,
) -> InventoryForecastBridge:
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Identity Bridge CSVは1 byte以上1 MiB以下です")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), strict=True)
        if reader.fieldnames != HEADER:
            raise ValueError("Identity Bridge CSVの列がtemplateと一致しません")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("Identity Bridge CSVはUTF-8形式で保存してください") from exc
    if not rows or len(rows) > 1000:
        raise ValueError("Identity Bridge CSVの行数が不正です")
    if any(row.get("確認メモ") != "確認済み" or None in row for row in rows):
        raise ValueError("Identity Bridge CSVの全行を確認済みにしてください")
    try:
        records = [
            (
                row["JAN"],
                row["warehouse_id"],
                row["canonical_product_id"],
                row["forecast_center_id"],
                date.fromisoformat(row["effective_from"]),
                None if not row["effective_to"] else date.fromisoformat(row["effective_to"]),
            )
            for row in rows
        ]
    except ValueError as exc:
        raise ValueError("Identity Bridge CSVの有効期間が不正です") from exc
    return build_inventory_forecast_bridge(
        records=records,
        created_by=created_by,
        reason=reason,
        created_at=created_at,
    )
