"""UI起点mappingドライランjobの永続契約。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MappingDryRunJob:
    job_id: str
    source_path: str
    mapping_id: str
    requested_by: str
    status: str
    sample_rows: int
    requested_at: str
    started_at: str | None = None
    finished_at: str | None = None
    dry_run_id: str | None = None
    outcome: str | None = None
    report_sha256: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class MappingDryRunBatch:
    batch_id: str
    source_prefix: str
    mapping_id: str
    requested_by: str
    sample_rows: int
    requested_at: str
    selected_count: int
    excluded_count: int


class MappingDryRunJobStore(Protocol):
    def enqueue(
        self, source_path: str, mapping_id: str, requested_by: str, sample_rows: int
    ) -> MappingDryRunJob: ...

    def get_job(self, job_id: str) -> MappingDryRunJob | None: ...
    def list_jobs(self) -> list[MappingDryRunJob]: ...
    def claim(self) -> MappingDryRunJob | None: ...

    def complete(self, job_id: str, dry_run_id: str, outcome: str, report_sha256: str) -> None: ...

    def fail(self, job_id: str, error_code: str) -> None: ...
