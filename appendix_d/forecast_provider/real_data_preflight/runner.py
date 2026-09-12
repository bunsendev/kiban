"""filesystemとPostgreSQLのプリフライト判定を統合する。"""

from __future__ import annotations

import platform
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .contracts import (
    EXPECTED_POSTGRES_MAJOR,
    REPORT_FORMAT_VERSION,
    REQUIRED_RELATIONS,
    SUITE_ID,
    PreflightRoots,
    public_policy,
)
from .database import inspect_database
from .filesystem import inspect_filesystem
from .report import fingerprint, publish_report


def _check(check_id: str, passed: bool, actual, expected) -> dict:
    return {
        "check_id": check_id,
        "status": "PASSED" if passed else "FAILED",
        "actual": actual,
        "expected": expected,
    }


def collect_preflight(
    roots: PreflightRoots,
    application_root: Path,
    postgres_dsn: str,
    *,
    filesystem_reader: Callable = inspect_filesystem,
    database_reader: Callable[[str], dict] = inspect_database,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    roots.validate(application_root)
    filesystem = filesystem_reader(roots.requirements(), application_root)
    database = database_reader(postgres_dsn)
    conditions = {
        "suite_id": SUITE_ID,
        "postgres_major": EXPECTED_POSTGRES_MAJOR,
        "required_relations": list(REQUIRED_RELATIONS),
        "filesystem_policy": public_policy(),
    }
    all_present = all(item["exists"] and item["directory"] for item in filesystem)
    all_readable = all(item["readable"] for item in filesystem)
    no_symlinks = all(not item["contains_symlink"] for item in filesystem)
    no_overlaps = all(not item["overlaps"] for item in filesystem)
    outside_application = all(item["outside_application_root"] for item in filesystem)
    access_matches = all(item["writable"] == item["expected_writable"] for item in filesystem)
    checks = [
        _check("ROOTS_PRESENT", all_present, all_present, True),
        _check("ROOTS_READABLE", all_readable, all_readable, True),
        _check("ROOTS_NO_SYMLINK", no_symlinks, no_symlinks, True),
        _check("ROOTS_DISJOINT", no_overlaps, no_overlaps, True),
        _check("ROOTS_OUTSIDE_APPLICATION", outside_application, outside_application, True),
        _check("ROOT_ACCESS_BOUNDARY", access_matches, access_matches, True),
        _check("POSTGRES_REACHABLE", database["reachable"], database["reachable"], True),
        _check(
            "POSTGRES_VERSION",
            database["server_major"] == EXPECTED_POSTGRES_MAJOR,
            database["server_major"],
            EXPECTED_POSTGRES_MAJOR,
        ),
        _check(
            "POSTGRES_SCHEMA",
            not database["missing_relations"]
            and database["present_relation_count"] == len(REQUIRED_RELATIONS),
            {
                "present": database["present_relation_count"],
                "missing": database["missing_relations"],
            },
            {"present": len(REQUIRED_RELATIONS), "missing": []},
        ),
        _check(
            "POSTGRES_PRIVILEGES",
            not database["insufficient_privileges"] and database["reachable"],
            database["insufficient_privileges"],
            [],
        ),
    ]
    outcome = "READY_FOR_DATA" if all(item["status"] == "PASSED" for item in checks) else "BLOCKED"
    return {
        "format_version": REPORT_FORMAT_VERSION,
        "preflight_id": fingerprint(conditions),
        "checked_at": now().astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "outcome": outcome,
        "conditions": conditions,
        "evidence": {
            "filesystem": filesystem,
            "postgres": database,
            "runtime": {
                "python_version": platform.python_version(),
                "platform": platform.system(),
                "machine": platform.machine(),
            },
        },
        "checks": checks,
        "limitations": [
            "実データを読まず、受入環境の技術的な投入準備だけを判定する。",
            "READY_FOR_DATAは実データ受入、予測精度、業務承認を意味しない。",
            "host側のbackup、監視、復旧訓練は別途確認する。",
        ],
    }


def run_preflight(
    roots: PreflightRoots,
    application_root: Path,
    postgres_dsn: str,
) -> dict:
    payload = collect_preflight(roots, application_root, postgres_dsn)
    report_uri, report_sha256 = publish_report(payload, roots.report_root)
    return {
        "preflight_id": payload["preflight_id"],
        "outcome": payload["outcome"],
        "report_uri": report_uri,
        "report_sha256": report_sha256,
    }
