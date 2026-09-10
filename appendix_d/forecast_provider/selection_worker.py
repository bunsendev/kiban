"""重要品目候補算出Worker CLI。"""

import argparse
import time

from .daily import PostgresDailyStore, SqliteDailyStore
from .master import PostgresMasterStore
from .operations.worker_config import add_database_arguments, postgres_dsn
from .selection import PostgresSelectionStore, SelectionProcessor, SqliteSelectionStore


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    add_database_arguments(value)
    value.add_argument("--once", action="store_true")
    value.add_argument("--poll-seconds", type=float, default=2.0)
    return value


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    dsn = postgres_dsn(args)
    if args.sqlite:
        daily = SqliteDailyStore(args.sqlite)
        store = SqliteSelectionStore(args.sqlite)
    else:
        PostgresMasterStore(dsn)
        daily = PostgresDailyStore(dsn)
        store = PostgresSelectionStore(dsn)
    processor = SelectionProcessor(store, daily)
    while True:
        processor.process_next()
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
