"""採用済み正規化行を版付きJAN対応で日次数量へ集計する。"""

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal


def aggregate_shipments(
    sources: list[dict],
    jan_mappings: list[dict],
    start: date,
    end: date,
    as_of: datetime,
) -> dict[tuple[str, str, date], dict]:
    as_of = as_of.astimezone(UTC)
    quantities = defaultdict(lambda: Decimal(0))
    availability: dict[tuple[str, str, date], datetime | None] = {}
    for source in sources:
        for row in source["rows"]:
            if row["status"] != "ACCEPTED":
                continue
            shipment_date = date.fromisoformat(row["shipment_date"])
            if not start <= shipment_date <= end:
                continue
            observed_at = _time(row["available_at"])
            if observed_at is None or observed_at.astimezone(UTC) > as_of:
                continue
            product_id = _resolve_jan(row["raw_jan"], shipment_date, jan_mappings)
            key = (product_id, row["center_id"], shipment_date)
            quantities[key] += Decimal(row["quantity"])
            previous = availability.get(key)
            if observed_at is not None and (previous is None or observed_at > previous):
                availability[key] = observed_at
            else:
                availability.setdefault(key, previous)
    return {
        key: {
            "raw_quantity": quantity,
            "available_at": None
            if availability.get(key) is None
            else availability[key].astimezone(UTC).isoformat(),
        }
        for key, quantity in quantities.items()
    }


def _resolve_jan(jan: str, target: date, mappings: list[dict]) -> str:
    matches = [
        item
        for item in mappings
        if item["jan"] == jan
        and date.fromisoformat(item["valid_from"]) <= target
        and (item["valid_to"] is None or target <= date.fromisoformat(item["valid_to"]))
    ]
    if len(matches) != 1:
        raise ValueError(f"JAN {jan} の{target.isoformat()}時点の対応が一意に確定しません")
    return matches[0]["canonical_product_id"]


def _time(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("available_atはtimezone付き日時です")
    return parsed
