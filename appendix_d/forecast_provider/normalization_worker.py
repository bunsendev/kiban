"""出荷行正規化をHTTP外で実行するWorker CLI。"""

import argparse
import time

from .ingestion import PostgresIngestionStore, SqliteIngestionStore
from .normalization import (
    NormalizationProcessor,
    PostgresNormalizationStore,
    SqliteNormalizationStore,
)
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
    if args.sqlite:
        ingestion = SqliteIngestionStore(args.sqlite)
        normalization = SqliteNormalizationStore(args.sqlite)
    else:
        ingestion = PostgresIngestionStore(dsn)
        normalization = PostgresNormalizationStore(dsn)
    processor = NormalizationProcessor(normalization, ingestion)
    while True:
        processor.process_next()
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
