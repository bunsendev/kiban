"""リカバリ訓練の公開契約。"""

from dataclasses import dataclass
from pathlib import Path

REPORT_SCHEMA_VERSION = "kiban-postgres-recovery-drill/v1"
CHECK_NAMES = (
    "archive_verified",
    "source_stable",
    "scratch_isolated",
    "restore_completed",
    "fingerprint_matched",
    "scratch_removed",
)
CHECK_STATUSES = frozenset({"PASSED", "FAILED", "NOT_RUN"})


@dataclass(frozen=True)
class DatabaseFingerprint:
    sha256: str
    relation_count: int
    postgres_major: int


@dataclass(frozen=True)
class DrillResult:
    outcome: str
    report_path: Path
    report_sha256: str
