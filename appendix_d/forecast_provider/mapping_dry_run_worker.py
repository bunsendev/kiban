"""UI起点mappingドライランをHTTP外で実行するWorker CLI。"""

import argparse
import time
from pathlib import Path

from .mapping_dry_run import (
    MappingDryRunProcessor,
    PostgresMappingDryRunJobStore,
    SqliteMappingDryRunJobStore,
)
from .normalization import PostgresNormalizationStore, SqliteNormalizationStore
from .operations.worker_config import add_database_arguments, postgres_dsn


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    add_database_arguments(value)
    value.add_argument("--input-root", type=Path, required=True)
    value.add_argument("--output-root", type=Path, required=True)
    value.add_argument("--once", action="store_true")
    value.add_argument("--poll-seconds", type=float, default=2.0)
    return value


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    dsn = postgres_dsn(args)
    if args.sqlite:
        jobs = SqliteMappingDryRunJobStore(args.sqlite)
        mappings = SqliteNormalizationStore(args.sqlite)
    else:
        jobs = PostgresMappingDryRunJobStore(dsn)
        mappings = PostgresNormalizationStore(dsn)
    processor = MappingDryRunProcessor(
        jobs, mappings, args.input_root, args.output_root
    )
    while True:
        processor.process_next()
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
