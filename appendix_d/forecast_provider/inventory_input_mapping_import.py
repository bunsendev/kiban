"""確認済みInventory Input Mappingを正式登録するCLI。"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from .inventory_foundation import (
    PostgresInventoryFoundationStore,
    SqliteInventoryFoundationStore,
    parse_confirmed_input_mapping_csv,
)
from .inventory_foundation.domain import canonical_datetime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="確認済みInventory Input Mappingの正式登録")
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    imported = parse_confirmed_input_mapping_csv(
        args.csv.read_bytes(),
        created_by=args.created_by,
        reason=args.reason,
        created_at=datetime.now(UTC),
    )
    store = (
        SqliteInventoryFoundationStore(args.sqlite)
        if args.sqlite is not None
        else PostgresInventoryFoundationStore(args.postgres_dsn)
    )
    store.put_mapping(imported.mapping)
    stored = store.get_mapping(imported.mapping.mapping_version)
    assert stored is not None
    result = {
        "mapping_version": stored.mapping_version,
        "content_sha256": imported.content_sha256,
        "product_identifier_kind": stored.product_identifier_kind.value,
        "product_mapping_version": stored.product_mapping_version,
        "location_master_version": stored.location_master_version,
        "normalized_unit": stored.normalized_unit.value,
        "created_by": stored.created_by,
        "reason": stored.reason,
        "created_at": canonical_datetime(stored.created_at),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
