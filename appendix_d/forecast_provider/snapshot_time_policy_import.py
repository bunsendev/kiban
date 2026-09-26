"""確認済みsnapshot時刻policyを正式登録するCLI。"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from .inventory_foundation import (
    PostgresInventoryFoundationStore,
    SqliteInventoryFoundationStore,
    parse_confirmed_snapshot_time_policy_csv,
)
from .inventory_foundation.domain import canonical_datetime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="確認済みsnapshot時刻policyの正式登録")
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    policy = parse_confirmed_snapshot_time_policy_csv(
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
    store.put_snapshot_time_policy(policy)
    stored = store.get_snapshot_time_policy(policy.policy_version)
    assert stored is not None
    result = {
        "policy_version": stored.policy_version,
        "content_sha256": stored.content_sha256,
        "source_kind": stored.source_kind.value,
        "cutoff_time": stored.cutoff_time.isoformat(),
        "timezone_name": stored.timezone_name,
        "created_by": stored.created_by,
        "reason": stored.reason,
        "created_at": canonical_datetime(stored.created_at),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
