"""復元元を書き換えないPostgreSQL隔離リカバリ訓練。"""

import platform
import time
from datetime import UTC, datetime
from pathlib import Path

from ..db_archive import (
    _verified_archive,
    backup_database,
    connection_settings,
    verify_backup,
)
from .contracts import CHECK_NAMES, REPORT_SCHEMA_VERSION, DrillResult
from .fingerprint import database_fingerprint
from .report import publish_report
from .scratch import (
    create_scratch,
    drop_scratch,
    generate_scratch_name,
    restore_scratch,
    scratch_connection,
)


class DrillFailure(RuntimeError):
    def __init__(self, stage: str):
        self.stage = stage
        super().__init__(stage)


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1_000))


def run_recovery_drill(dsn: str, backup_dir: Path, report_dir: Path) -> DrillResult:
    """backupから内部生成DBへ復元し、元DBとの一致を検査する。"""

    total_started = time.perf_counter()
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    checks = dict.fromkeys(CHECK_NAMES, "NOT_RUN")
    durations: dict[str, int] = {}
    source_before = source_after = restored = None
    archive_sha256 = None
    failure_stage = failure_type = None
    source = target = None
    current_stage = "configuration"

    try:
        source = connection_settings(dsn)
        target = scratch_connection(source, generate_scratch_name())

        current_stage = "source_fingerprint_before"
        step = time.perf_counter()
        source_before = database_fingerprint(source)
        durations[current_stage] = _elapsed_ms(step)

        current_stage = "backup"
        step = time.perf_counter()
        manifest_path = backup_database(dsn, backup_dir)
        durations[current_stage] = _elapsed_ms(step)

        current_stage = "archive_verified"
        step = time.perf_counter()
        manifest = verify_backup(manifest_path)
        archive, _ = _verified_archive(manifest_path)
        archive_sha256 = manifest["sha256"]
        checks[current_stage] = "PASSED"
        durations[current_stage] = _elapsed_ms(step)

        current_stage = "source_fingerprint_after"
        step = time.perf_counter()
        source_after = database_fingerprint(source)
        durations[current_stage] = _elapsed_ms(step)
        if source_before != source_after:
            checks["source_stable"] = "FAILED"
            raise DrillFailure("source_stable")
        checks["source_stable"] = "PASSED"

        current_stage = "scratch_isolated"
        step = time.perf_counter()
        create_scratch(source, target)
        checks[current_stage] = "PASSED"
        durations[current_stage] = _elapsed_ms(step)

        current_stage = "restore_completed"
        step = time.perf_counter()
        restore_scratch(target, archive)
        checks[current_stage] = "PASSED"
        durations[current_stage] = _elapsed_ms(step)

        current_stage = "restored_fingerprint"
        step = time.perf_counter()
        restored = database_fingerprint(target)
        durations[current_stage] = _elapsed_ms(step)
        if restored != source_after:
            checks["fingerprint_matched"] = "FAILED"
            raise DrillFailure("fingerprint_matched")
        checks["fingerprint_matched"] = "PASSED"
    except (OSError, ValueError, RuntimeError) as exc:
        failure_stage = exc.stage if isinstance(exc, DrillFailure) else current_stage
        failure_type = type(exc).__name__
        if current_stage in checks and checks[current_stage] == "NOT_RUN":
            checks[current_stage] = "FAILED"
    finally:
        cleanup_started = time.perf_counter()
        if source is not None and target is not None:
            try:
                drop_scratch(source, target)
                checks["scratch_removed"] = "PASSED"
            except (OSError, ValueError, RuntimeError) as exc:
                checks["scratch_removed"] = "FAILED"
                failure_stage = "scratch_removed"
                failure_type = type(exc).__name__
        else:
            checks["scratch_removed"] = "PASSED"
        durations["scratch_removed"] = _elapsed_ms(cleanup_started)

    outcome = (
        "DRILL_PASSED"
        if all(status == "PASSED" for status in checks.values())
        else "DRILL_FAILED"
    )
    payload = {
        "archive_sha256": archive_sha256,
        "checks": checks,
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "durations_ms": {**durations, "total": _elapsed_ms(total_started)},
        "environment": {
            "implementation": platform.python_implementation(),
            "python": platform.python_version(),
            "system": platform.system(),
        },
        "failure_stage": failure_stage,
        "failure_type": failure_type,
        "outcome": outcome,
        "postgres_major": source_after.postgres_major if source_after else None,
        "relation_count": source_after.relation_count if source_after else None,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "restored_fingerprint_sha256": restored.sha256 if restored else None,
        "source_fingerprint_sha256": source_after.sha256 if source_after else None,
        "started_at": started_at,
        "scope": "isolated_technical_recovery_drill",
    }
    report_path, checksum = publish_report(payload, report_dir)
    return DrillResult(outcome, report_path, checksum)
