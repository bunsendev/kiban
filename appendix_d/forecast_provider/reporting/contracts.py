"""比較CSVと採用判断の永続契約。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExportRecord:
    export_id: str
    format_version: int
    condition_fingerprint: str
    comparison_id: str
    export_version: str
    baseline_run_id: str
    requested_by: str
    output_uri: str
    output_sha256: str
    row_count: int
    created_at: str


@dataclass(frozen=True)
class AdoptionRecord:
    adoption_id: str
    format_version: int
    condition_fingerprint: str
    adoption_version: str
    comparison_id: str
    acceptance_case_id: str | None
    decision: str
    selected_run_id: str | None
    fallback_run_id: str | None
    target: dict
    decided_by: str
    reason: str
    decided_at: str


class ReportingStore(Protocol):
    def put_export(self, value: ExportRecord) -> ExportRecord: ...
    def get_export(self, export_id: str) -> ExportRecord | None: ...
    def list_exports(self, comparison_id: str | None = None) -> list[ExportRecord]: ...
    def put_adoption(self, value: AdoptionRecord) -> AdoptionRecord: ...
    def get_adoption(self, adoption_id: str) -> AdoptionRecord | None: ...
    def list_adoptions(self, comparison_id: str | None = None) -> list[AdoptionRecord]: ...
