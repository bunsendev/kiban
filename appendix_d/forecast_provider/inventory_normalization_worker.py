"""在庫正規化Worker CLI。"""

import argparse
import time
from pathlib import Path

from .inventory_normalization import (
    InventoryNormalizationProcessor,
    PostgresInventoryNormalizationStore,
    SqliteInventoryNormalizationStore,
)
from .operations.worker_config import add_database_arguments, postgres_dsn


def main(argv=None):
    parser = argparse.ArgumentParser()
    add_database_arguments(parser)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    store = (
        SqliteInventoryNormalizationStore(args.sqlite)
        if args.sqlite
        else PostgresInventoryNormalizationStore(postgres_dsn(args))
    )
    processor = InventoryNormalizationProcessor(store, args.input_root)
    while True:
        processor.process_next()
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
