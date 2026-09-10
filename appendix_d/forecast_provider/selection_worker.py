"""重要品目候補算出Worker CLI。"""

import argparse
import time
from pathlib import Path

from .daily import PostgresDailyStore, SqliteDailyStore
from .master import PostgresMasterStore
from .selection import PostgresSelectionStore, SelectionProcessor, SqliteSelectionStore


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    database = value.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    value.add_argument("--once", action="store_true")
    value.add_argument("--poll-seconds", type=float, default=2.0)
    return value


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.sqlite:
        daily = SqliteDailyStore(args.sqlite)
        store = SqliteSelectionStore(args.sqlite)
    else:
        PostgresMasterStore(args.postgres_dsn)
        daily = PostgresDailyStore(args.postgres_dsn)
        store = PostgresSelectionStore(args.postgres_dsn)
    processor = SelectionProcessor(store, daily)
    while True:
        processor.process_next()
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
