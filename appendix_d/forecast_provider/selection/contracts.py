"""重要品目候補と確定選定版の永続契約。"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

SelectionScope = Literal["INITIAL", "FULL"]


@dataclass(frozen=True)
class CandidateJob:
    candidate_job_id: str
    format_version: int
    condition_fingerprint: str
    definition: dict
    status: str
    error: str | None = None


@dataclass(frozen=True)
class SelectionCandidate:
    candidate_job_id: str
    canonical_product_id: str
    rank: int
    total_quantity: Decimal
    quantity_share: Decimal | None
    coefficient_of_variation: Decimal | None
    zero_rate: Decimal | None
    missing_rate: Decimal | None
    usable_days: int
    handled_days: int
    jan_changed: bool
    business_designated: bool
    center_ids: tuple[str, ...]
    tags: tuple[str, ...]
    eligible: bool
    ineligibility_reason: str | None = None


@dataclass(frozen=True)
class SelectionVersion:
    selection_id: str
    format_version: int
    condition_fingerprint: str
    definition: dict
    selected_at: str


@dataclass(frozen=True)
class SelectionItem:
    selection_id: str
    canonical_product_id: str
    center_ids: tuple[str, ...]
    reason: str


class SelectionStore(Protocol):
    def put_candidate_job(self, value: CandidateJob) -> CandidateJob: ...
    def get_candidate_job(self, candidate_job_id: str) -> CandidateJob | None: ...
    def list_candidate_jobs(self) -> list[CandidateJob]: ...
    def claim(self) -> CandidateJob | None: ...
    def complete(self, candidate_job_id: str, candidates: list[SelectionCandidate]) -> None: ...
    def fail(self, candidate_job_id: str, error: str) -> None: ...
    def list_candidates(self, candidate_job_id: str) -> list[SelectionCandidate]: ...
    def put_selection(self, value: SelectionVersion) -> SelectionVersion: ...
    def get_selection(self, selection_id: str) -> SelectionVersion | None: ...
    def list_selections(self) -> list[SelectionVersion]: ...
    def list_selection_items(self, selection_id: str) -> list[SelectionItem]: ...
