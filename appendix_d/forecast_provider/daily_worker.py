"""日次状態とdataset snapshotを生成するWorker CLI。"""

import argparse
import time
from pathlib import Path

from .catalog import PostgresCatalogStore, SqliteCatalogStore
from .daily import DailyProcessor, PostgresDailyStore, SqliteDailyStore
from .master import PostgresMasterStore


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    database = value.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    value.add_argument("--output-root", type=Path, required=True)
    value.add_argument("--once", action="store_true")
    value.add_argument("--poll-seconds", type=float, default=2.0)
    return value


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.sqlite:
        catalog = SqliteCatalogStore(args.sqlite)
        store = SqliteDailyStore(args.sqlite)
    else:
        catalog = PostgresCatalogStore(args.postgres_dsn)
        PostgresMasterStore(args.postgres_dsn)
        store = PostgresDailyStore(args.postgres_dsn)
    processor = DailyProcessor(store, catalog, args.output_root)
    while True:
        processor.process_next()
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
