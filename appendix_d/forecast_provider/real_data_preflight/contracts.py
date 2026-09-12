"""実データ受入プリフライトの固定契約。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPORT_FORMAT_VERSION = 1
SUITE_ID = "real-data-preflight/v1"
EXPECTED_POSTGRES_MAJOR = 17

REQUIRED_RELATIONS = (
    "acceptance_cases",
    "acceptance_checks",
    "acceptance_decisions",
    "canonical_products",
    "closed_days",
    "column_mappings",
    "daily_build_jobs",
    "daily_file_completeness",
    "daily_values",
    "dataset_snapshots",
    "file_schedules",
    "handling_periods",
    "import_jobs",
    "jan_mappings",
    "matching_candidates",
    "matching_decisions",
    "matching_jobs",
    "normalization_jobs",
    "planned_files",
    "quantity_reconciliations",
    "shipment_rows",
    "source_file_selections",
    "source_files",
)


@dataclass(frozen=True)
class RootRequirement:
    root_id: str
    path: Path
    writable: bool


@dataclass(frozen=True)
class PreflightRoots:
    """原本本文やpathをレポートへ出さずに検査する5つのroot。"""

    import_root: Path
    archive_root: Path
    snapshot_root: Path
    acceptance_root: Path
    report_root: Path

    def requirements(self) -> tuple[RootRequirement, ...]:
        return (
            RootRequirement("import_input", self.import_root, False),
            RootRequirement("raw_archive", self.archive_root, True),
            RootRequirement("snapshot", self.snapshot_root, True),
            RootRequirement("acceptance_report", self.acceptance_root, True),
            RootRequirement("preflight_report", self.report_root, True),
        )

    def validate(self, application_root: Path) -> None:
        values = [requirement.path for requirement in self.requirements()]
        if not application_root.is_absolute() or any(not value.is_absolute() for value in values):
            raise ValueError("application rootとdata rootは絶対pathで指定します")


def public_policy() -> dict:
    return {
        "application_boundary": "outside",
        "root_access": {
            "import_input": "read_only",
            "raw_archive": "read_write",
            "snapshot": "read_write",
            "acceptance_report": "read_write",
            "preflight_report": "read_write",
        },
        "root_overlap": "forbidden",
        "root_symlink": "forbidden",
    }
