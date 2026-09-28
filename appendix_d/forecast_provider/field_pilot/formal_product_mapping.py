"""現場で確認したJANだけを版付き正式商品対応表へ登録する。"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path

from ..inventory_foundation.product_mappings import parse_confirmed_product_mapping_csv
from .product_review import unresolved_products


def publish_confirmed_product_mapping(
    inbox_root: Path, settings_store, inventory_store, *, actor: str, reason: str,
    now: datetime | None = None,
) -> dict:
    if not actor.strip() or not reason.strip() or len(actor) > 100 or len(reason) > 500:
        raise ValueError("PRODUCT_MAPPING_AUDIT_INVALID")
    review = unresolved_products(inbox_root, settings_store)
    if not review["complete"]:
        raise ValueError("PRODUCT_MAPPING_SOURCE_INCOMPLETE")
    eligible = [
        item for item in review["confirmed_items"]
        if item["evidence_status"] != "JAN_CONFLICT"
    ]
    if not eligible:
        raise ValueError("PRODUCT_MAPPING_CONFIRMED_EMPTY")
    document = io.StringIO()
    writer = csv.writer(document, lineterminator="\n")
    writer.writerow(("商品コード", "商品名", "JAN", "確認メモ"))
    evidence = []
    for item in sorted(eligible, key=lambda value: value["product_code"]):
        code = item["product_code"]
        record = settings_store.current("JAN_MAPPING", code)
        if record is None or record["value"]["jan"] != item["jan"]:
            raise ValueError("PRODUCT_MAPPING_VERSION_CHANGED")
        writer.writerow((code, record["value"]["product_name"], item["jan"], "確認済み"))
        evidence.append(f"{code}:{record['version']}")
    evidence_hash = hashlib.sha256("\n".join(evidence).encode("utf-8")).hexdigest()
    parsed = parse_confirmed_product_mapping_csv(
        document.getvalue().encode("utf-8"),
        source_reference=f"field-pilot-settings:{evidence_hash}",
        created_by=actor.strip(), reason=reason.strip(),
        created_at=now or datetime.now(UTC),
    )
    inventory_store.put_product_mapping(parsed.version, parsed.records)
    return {
        "product_mapping_version": parsed.version.product_mapping_version,
        "published_count": len(parsed.records),
        "unresolved_count": review["unresolved_count"],
        "conflict_count": review["confirmed_count"] - len(eligible),
        "source_reference": parsed.version.source_reference,
    }
