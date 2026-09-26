"""確認済みJAN対応表をInventory Foundationへ登録するCLI。"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from .inventory_foundation import (
    PostgresInventoryFoundationStore,
    SqliteInventoryFoundationStore,
    parse_confirmed_product_mapping_csv,
    serialize_product_mapping_version,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="確認済みJAN対応表の正式mapping登録")
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--source-reference")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    content = args.csv.read_bytes()
    source_reference = args.source_reference or f"product-jan-{hashlib.sha256(content).hexdigest()}"
    imported = parse_confirmed_product_mapping_csv(
        content,
        source_reference=source_reference,
        created_by=args.created_by,
        reason=args.reason,
        created_at=datetime.now(UTC),
    )
    store = (
        SqliteInventoryFoundationStore(args.sqlite)
        if args.sqlite is not None
        else PostgresInventoryFoundationStore(args.postgres_dsn)
    )
    store.put_product_mapping(imported.version, imported.records)
    stored_version = store.get_product_mapping_version(
        imported.version.product_mapping_version
    )
    assert stored_version is not None
    result = serialize_product_mapping_version(stored_version)
    result["canonical_product_linked_count"] = sum(
        record.canonical_product_id is not None for record in imported.records
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
