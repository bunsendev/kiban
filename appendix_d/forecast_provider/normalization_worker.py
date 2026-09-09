"""出荷行正規化をHTTP外で実行するWorker CLI。"""

import argparse
import time
from pathlib import Path

from .ingestion import PostgresIngestionStore, SqliteIngestionStore
from .normalization import (
    NormalizationProcessor,
    PostgresNormalizationStore,
    SqliteNormalizationStore,
)


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
        ingestion = SqliteIngestionStore(args.sqlite)
        normalization = SqliteNormalizationStore(args.sqlite)
    else:
        ingestion = PostgresIngestionStore(args.postgres_dsn)
        normalization = PostgresNormalizationStore(args.postgres_dsn)
    processor = NormalizationProcessor(normalization, ingestion)
    while True:
        processor.process_next()
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
