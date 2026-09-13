"""PostgreSQL backup/restore/recovery drill CLI。"""

import argparse
import json
import os
import sys
from pathlib import Path

# 従来のimport先を互換維持する。subprocessも既存testの差し替え口として公開する。
from .db_archive import (
    SCHEMA_VERSION,
    backup_database,
    connection_settings,
    restore_database,
    subprocess,
    verify_backup,
)

__all__ = [
    "SCHEMA_VERSION",
    "backup_database",
    "connection_settings",
    "main",
    "restore_database",
    "subprocess",
    "verify_backup",
]


def _dsn_from_environment() -> str:
    value = os.environ.get("KIBAN_POSTGRES_DSN")
    file_name = os.environ.get("KIBAN_POSTGRES_DSN_FILE")
    if value and file_name:
        raise ValueError("KIBAN_POSTGRES_DSNとKIBAN_POSTGRES_DSN_FILEは併用できません")
    if file_name:
        path = Path(file_name)
        if not path.is_file() or not 0 < path.stat().st_size <= 8_192:
            raise ValueError("KIBAN_POSTGRES_DSN_FILEのサイズが不正です")
        value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError("KIBAN_POSTGRES_DSNまたはKIBAN_POSTGRES_DSN_FILEが必要です")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Yosoku Kiban PostgreSQL operations")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--output-dir", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--confirm-database", required=True)
    drill = commands.add_parser("drill")
    drill.add_argument("--backup-dir", type=Path, required=True)
    drill.add_argument("--report-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "backup":
            manifest = backup_database(_dsn_from_environment(), args.output_dir)
            response = {"manifest": str(manifest)}
        elif args.command == "verify":
            response = verify_backup(args.manifest)
        elif args.command == "restore":
            restore_database(
                _dsn_from_environment(), args.manifest, args.confirm_database
            )
            response = {"restored": True}
        else:
            from .recovery.runner import run_recovery_drill

            result = run_recovery_drill(
                _dsn_from_environment(), args.backup_dir, args.report_dir
            )
            response = {
                "outcome": result.outcome,
                "report": str(result.report_path),
                "report_sha256": result.report_sha256,
            }
            print(json.dumps(response, ensure_ascii=False, sort_keys=True))
            return 0 if result.outcome == "DRILL_PASSED" else 2
        print(json.dumps(response, ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
