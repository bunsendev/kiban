"""Worker CLI共通のdatabase指定。"""

import argparse
from pathlib import Path

from ..runtime_config import read_secret_file


def add_database_arguments(parser: argparse.ArgumentParser) -> None:
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    database.add_argument("--postgres-dsn-file", type=Path)


def postgres_dsn(args: argparse.Namespace) -> str | None:
    if args.sqlite:
        return None
    if args.postgres_dsn_file:
        return read_secret_file(args.postgres_dsn_file, "PostgreSQL DSN file", 8_192)
    return args.postgres_dsn
