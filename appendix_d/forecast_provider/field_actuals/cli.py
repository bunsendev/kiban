"""後日実績CSVの事前検証と原子的な追記。"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from ..field_learning import PostgresFieldLearningStore, SqliteFieldLearningStore
from .importer import MAX_CSV_BYTES, FieldActualImporter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shadow実績CSVを検証して台帳へ接続")
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--known-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--recorded-at", type=datetime.fromisoformat)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not args.csv.is_file() or not 0 < args.csv.stat().st_size <= MAX_CSV_BYTES:
        parser.error("CSVは存在する1 byte以上10 MiB以下のファイルです")
    store = (
        SqliteFieldLearningStore(args.sqlite) if args.sqlite is not None
        else PostgresFieldLearningStore(args.postgres_dsn)
    )
    plan = FieldActualImporter(store).prepare(
        args.csv.read_bytes(), source_version=args.source_version,
        known_at=args.known_at, recorded_at=args.recorded_at or datetime.now(UTC),
    )
    if args.apply:
        FieldActualImporter(store).apply(plan)
    print(json.dumps({
        "status": "APPLIED" if args.apply else "DRY_RUN",
        "source_version": plan.source_version,
        "source_sha256": plan.source_sha256,
        "known_at": plan.known_at.isoformat(),
        "row_count": len(plan.events),
        "case_ids": [event.case_id for event in plan.events],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
