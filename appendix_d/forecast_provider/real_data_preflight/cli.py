"""実データ受入プリフライトCLI。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..runtime_config import read_secret_file
from .contracts import PreflightRoots
from .runner import run_preflight


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="実データを読まずに受入環境を検査します")
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--postgres-dsn")
    database.add_argument("--postgres-dsn-file", type=Path)
    parser.add_argument("--application-root", type=Path, required=True)
    parser.add_argument("--import-root", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--acceptance-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dsn = (
            read_secret_file(args.postgres_dsn_file, "PostgreSQL DSN file", 8_192)
            if args.postgres_dsn_file
            else args.postgres_dsn
        )
        result = run_preflight(
            PreflightRoots(
                import_root=args.import_root,
                archive_root=args.archive_root,
                snapshot_root=args.snapshot_root,
                acceptance_root=args.acceptance_root,
                report_root=args.output_root,
            ),
            args.application_root,
            dsn,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["outcome"] == "READY_FOR_DATA" else 2


if __name__ == "__main__":
    raise SystemExit(main())
