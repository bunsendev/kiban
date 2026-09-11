"""予定完全性・日次状態・dataset buildの永続契約。"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

DailyState = Literal[
    "OBSERVED",
    "CONFIRMED_ZERO",
    "MISSING",
    "NOT_HANDLED",
    "CLOSED",
    "PARTIAL_OR_INVALID",
]
CompletenessStatus = Literal["COMPLETE", "MISSING", "PARTIAL_OR_INVALID"]


@dataclass(frozen=True)
class FileSchedule:
    schedule_id: str
    format_version: int
    content_hash: str
    definition: dict


@dataclass(frozen=True)
class ClosedDay:
    closed_day_id: str
    center_id: str
    closed_date: str
    closure_version: str
    available_at: str
    approved_by: str
    reason: str
    decided_at: str


@dataclass(frozen=True)
class DailyBuildJob:
    build_id: str
    format_version: int
    condition_fingerprint: str
    definition: dict
    status: str
    snapshot_id: str | None = None
    data_uri: str | None = None
    data_sha256: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class FileCompleteness:
    build_id: str
    center_id: str
    target_date: str
    status: CompletenessStatus
    expected_count: int
    valid_count: int
    zero_confirmable: bool
    available_at: str
    missing_paths: tuple[str, ...] = ()
    invalid_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class DailyValue:
    build_id: str
    canonical_product_id: str
    center_id: str
    ds: str
    unique_id: str
    raw_quantity: Decimal | None
    y: Decimal | None
    state: DailyState
    available_at: str
    issue: str | None = None


class DailyStore(Protocol):
    def put_schedule(self, value: FileSchedule) -> None: ...
    def get_schedule(self, schedule_id: str) -> FileSchedule | None: ...
    def put_closed_day(self, value: ClosedDay) -> None: ...
    def list_closed_days(self, closure_version: str | None = None) -> list[ClosedDay]: ...
    def put_job(self, value: DailyBuildJob) -> DailyBuildJob: ...
    def get_job(self, build_id: str) -> DailyBuildJob | None: ...
    def list_jobs(self) -> list[DailyBuildJob]: ...
    def claim(self) -> DailyBuildJob | None: ...
    def complete(
        self,
        build_id: str,
        completeness: list[FileCompleteness],
        values: list[DailyValue],
        snapshot_id: str,
        data_uri: str,
        data_sha256: str,
    ) -> None: ...
    def fail(self, build_id: str, error: str) -> None: ...
    def list_completeness(self, build_id: str) -> list[FileCompleteness]: ...
    def list_values(self, build_id: str) -> list[DailyValue]: ...
    def readiness_summary(self, build_id: str) -> dict: ...
    def list_values_page(
        self,
        build_id: str,
        *,
        state: str | None = None,
        canonical_product_id: str | None = None,
        center_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[int, list[DailyValue]]: ...
