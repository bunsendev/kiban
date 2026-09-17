"""Provider適合試験jobの永続契約。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ConformanceJob:
    job_id: str
    experiment_id: str
    provider_id: str
    model_id: str
    requested_by: str
    status: str
    requested_at: str
    started_at: str | None = None
    finished_at: str | None = None
    conformance_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class ConformanceJobStore(Protocol):
    def enqueue(
        self, experiment_id: str, provider_id: str, model_id: str, requested_by: str
    ) -> ConformanceJob: ...

    def get_job(self, job_id: str) -> ConformanceJob | None: ...
    def list_jobs(self, experiment_id: str | None = None) -> list[ConformanceJob]: ...
    def claim(self, provider_id: str) -> ConformanceJob | None: ...
    def complete(self, job_id: str, conformance_id: str) -> None: ...
    def fail(self, job_id: str, error_code: str, error_message: str) -> None: ...
