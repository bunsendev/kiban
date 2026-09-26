"""確認済みlocation masterをInventory Foundationへ登録するCLI。"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from .inventory_foundation import (
    LocationType,
    PostgresInventoryFoundationStore,
    SqliteInventoryFoundationStore,
    parse_confirmed_location_master_csv,
)
from .inventory_foundation.domain import canonical_datetime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="確認済みlocation masterの正式登録")
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    imported = parse_confirmed_location_master_csv(
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
    store.put_location_master(imported.version, imported.locations)
    stored = store.get_location_master_version(imported.version.location_master_version)
    assert stored is not None
    result = {
        "location_master_version": stored.location_master_version,
        "content_sha256": stored.content_sha256,
        "row_count": len(imported.locations),
        "factory_count": sum(
            value.location_type is LocationType.FACTORY for value in imported.locations
        ),
        "warehouse_count": sum(
            value.location_type is LocationType.WAREHOUSE for value in imported.locations
        ),
        "created_by": stored.created_by,
        "reason": stored.reason,
        "created_at": canonical_datetime(stored.created_at),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
