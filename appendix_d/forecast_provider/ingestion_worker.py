"""原本取込をHTTP外で実行するWorker CLI。"""

import argparse
import time
from pathlib import Path

from .ingestion import ImportProcessor, PostgresIngestionStore, SqliteIngestionStore
from .operations.worker_config import add_database_arguments, postgres_dsn


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    add_database_arguments(value)
    value.add_argument("--input-root", type=Path, required=True)
    value.add_argument("--archive-root", type=Path, required=True)
    value.add_argument("--once", action="store_true")
    value.add_argument("--poll-seconds", type=float, default=2.0)
    return value


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    dsn = postgres_dsn(args)
    store = (
        SqliteIngestionStore(args.sqlite)
        if args.sqlite
        else PostgresIngestionStore(dsn)
    )
    processor = ImportProcessor(store, args.input_root, args.archive_root)
    while True:
        processor.process_next()
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
