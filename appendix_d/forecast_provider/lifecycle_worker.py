"""月次Lifecycle cycleを登録するscheduler CLI。"""

import argparse
import time

from .lifecycle import PostgresLifecycleStore, SqliteLifecycleStore
from .lifecycle.scheduler import enqueue_due_cycles
from .operations.worker_config import add_database_arguments, postgres_dsn


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    add_database_arguments(value)
    value.add_argument("--once", action="store_true")
    value.add_argument("--poll-seconds", type=float, default=60.0)
    return value


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.poll_seconds <= 0:
        raise ValueError("poll-secondsは正数です")
    dsn = postgres_dsn(args)
    store = SqliteLifecycleStore(args.sqlite) if args.sqlite else PostgresLifecycleStore(dsn)
    while True:
        enqueue_due_cycles(store)
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

