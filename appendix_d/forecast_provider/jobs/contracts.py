"""永続run台帳と再開Workerの製品非依存契約。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

RunStatus = Literal["QUEUED", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"]
OriginStatus = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]


@dataclass(frozen=True)
class RunDefinition:
    run_id: str
    experiment_id: str
    condition_fingerprint: str
    provider_id: str
    model_name: str
    seed: int


@dataclass(frozen=True)
class OriginDefinition:
    origin_date: date
    cutoff_at: datetime


@dataclass(frozen=True)
class Expectation:
    unique_id: str
    origin_date: date
    target_date: date
    horizon: int


@dataclass(frozen=True)
class ForecastValue:
    unique_id: str
    origin_date: date
    target_date: date
    horizon: int
    forecast_kind: Literal["POINT", "QUANTILE"]
    quantile: Decimal | None
    yhat_raw: Decimal
    yhat: Decimal


@dataclass(frozen=True)
class OriginOutput:
    values: tuple[ForecastValue, ...]
    model_artifact: str | None = None
    context_artifact: str | None = None


@dataclass(frozen=True)
class OriginLease:
    run_id: str
    origin: OriginDefinition
    attempt: int
    worker_id: str
    lease_token: str
    leased_until: datetime


class RunStore(Protocol):
    def create_run(
        self,
        definition: RunDefinition,
        origins: tuple[OriginDefinition, ...],
        expectations: tuple[Expectation, ...],
    ) -> None: ...

    def start_or_resume(self, run_id: str, condition_fingerprint: str) -> None: ...

    def claim_next_origin(
        self, run_id: str, worker_id: str, lease_seconds: int
    ) -> OriginLease | None: ...

    def heartbeat(self, lease: OriginLease, lease_seconds: int) -> OriginLease: ...

    def reclaim_expired(self, run_id: str, *, now: datetime | None = None) -> int: ...

    def complete_origin(self, lease: OriginLease, output: OriginOutput) -> None: ...

    def fail_origin(self, lease: OriginLease, error: str, *, retryable: bool) -> None: ...

    def finish_run(self, run_id: str) -> RunStatus: ...

    def cancellation_requested(self, run_id: str) -> bool: ...


OriginExecutor = Callable[[OriginLease], OriginOutput]
