"""JAN名寄せ候補をHTTP外で生成するWorker CLI。"""

import argparse
import time

from .master import MatchingProcessor, PostgresMasterStore, SqliteMasterStore
from .operations.worker_config import add_database_arguments, postgres_dsn


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    add_database_arguments(value)
    value.add_argument("--once", action="store_true")
    value.add_argument("--poll-seconds", type=float, default=2.0)
    return value


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    dsn = postgres_dsn(args)
    store = (
        SqliteMasterStore(args.sqlite) if args.sqlite else PostgresMasterStore(dsn)
    )
    processor = MatchingProcessor(store)
    while True:
        processor.process_next()
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
