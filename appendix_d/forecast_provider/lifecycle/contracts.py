"""継続学習、昇格、rollback、試験運用の永続契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

CycleStatus = Literal["QUEUED", "READY", "REJECTED", "PROMOTED", "FAILED"]
ChampionAction = Literal["INITIALIZED", "PROMOTED", "ROLLED_BACK"]
TrialDecision = Literal["CONTINUE", "COMPLETE", "ROLLBACK"]


@dataclass(frozen=True)
class LifecyclePlan:
    plan_id: str
    format_version: int
    condition_fingerprint: str
    plan_version: str
    adoption_id: str
    experiment_id: str
    initial_champion_run_id: str
    fallback_run_id: str
    schedule_day: int
    schedule_time: str
    timezone: str
    trial_start_date: date
    trial_end_date: date
    metric: str
    minimum_improvement_pct: float
    maximum_failure_rate: float
    created_by: str
    reason: str
    created_at: str


@dataclass(frozen=True)
class LifecycleCycle:
    cycle_id: str
    plan_id: str
    due_month: str
    scheduled_for: str
    status: CycleStatus
    challenger_run_id: str | None
    comparison_id: str | None
    score: dict | None
    failure_code: str | None
    created_at: str
    completed_at: str | None


@dataclass(frozen=True)
class ChampionEvent:
    event_id: str
    plan_id: str
    revision: int
    action: ChampionAction
    from_run_id: str | None
    to_run_id: str
    cycle_id: str | None
    comparison_id: str | None
    approved_by: str
    reason: str
    created_at: str


@dataclass(frozen=True)
class TrialForecastRecord:
    record_id: str
    plan_id: str
    run_id: str
    origin_date: date
    recorded_by: str
    recorded_at: str


@dataclass(frozen=True)
class TrialAssessment:
    assessment_id: str
    plan_id: str
    revision: int
    period_start: date
    period_end: date
    comparison_id: str
    evidence_kind: str
    decision: TrialDecision
    assessed_by: str
    reason: str
    created_at: str


class LifecycleStore(Protocol):
    def put_plan(
        self, plan: LifecyclePlan, initial_event: ChampionEvent
    ) -> LifecyclePlan: ...
    def get_plan(self, plan_id: str) -> LifecyclePlan | None: ...
    def list_plans(self) -> list[LifecyclePlan]: ...
    def put_cycle(self, cycle: LifecycleCycle) -> LifecycleCycle: ...
    def get_cycle(self, cycle_id: str) -> LifecycleCycle | None: ...
    def list_cycles(self, plan_id: str) -> list[LifecycleCycle]: ...
    def resolve_cycle(self, cycle: LifecycleCycle) -> LifecycleCycle: ...
    def append_champion_event(
        self,
        event: ChampionEvent,
        expected_revision: int,
        cycle_id: str | None = None,
    ) -> ChampionEvent: ...
    def list_champion_events(self, plan_id: str) -> list[ChampionEvent]: ...
    def put_trial_forecast(self, value: TrialForecastRecord) -> TrialForecastRecord: ...
    def list_trial_forecasts(self, plan_id: str) -> list[TrialForecastRecord]: ...
    def append_trial_assessment(
        self, value: TrialAssessment, expected_revision: int
    ) -> TrialAssessment: ...
    def list_trial_assessments(self, plan_id: str) -> list[TrialAssessment]: ...

