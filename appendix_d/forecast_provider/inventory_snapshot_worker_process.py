"""Phase 3S-3 inventory snapshot独立Worker process。"""

from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path

from .inventory_foundation.postgres import PostgresInventoryFoundationStore
from .inventory_foundation.sources import DirectoryInventorySourceReader
from .inventory_foundation.store import SqliteInventoryFoundationStore
from .inventory_foundation.worker import InventorySnapshotWorker


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="在庫CSV snapshot Worker")
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--worker-id", default=f"inventory-snapshot-{uuid.uuid4().hex[:12]}")
    parser.add_argument("--lease-seconds", type=int, default=300)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.lease_seconds < 1 or args.poll_seconds <= 0:
        raise SystemExit("lease-secondsとpoll-secondsは正数です")
    store = (
        SqliteInventoryFoundationStore(args.sqlite)
        if args.sqlite is not None
        else PostgresInventoryFoundationStore(args.postgres_dsn)
    )
    worker = InventorySnapshotWorker(
        store,
        DirectoryInventorySourceReader(args.source_root),
    )
    while True:
        result = worker.run_once(args.worker_id, lease_seconds=args.lease_seconds)
        if args.once:
            return 0
        if result is None:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
