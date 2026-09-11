"""採用判断、月次cycle、champion eventを結ぶLifecycleサービス。"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime

from ..catalog import CatalogStore
from ..evaluation_registry.contracts import EvaluationRegistryStore
from ..jobs.contracts import RunStore
from ..reporting.contracts import ReportingStore
from .contracts import LifecycleCycle, LifecyclePlan, LifecycleStore
from .domain import make_champion_event
from .plan_domain import make_plan
from .promotion import promotion_score
from .scheduler import enqueue_due_cycles
from .store import LifecycleStoreConflict

TERMINAL_STATUSES = frozenset({"SUCCEEDED", "PARTIAL", "FAILED"})


class LifecycleNotFound(KeyError):
    pass


class LifecycleConflict(ValueError):
    pass


class LifecycleService:
    def __init__(
        self,
        runs: RunStore,
        catalog: CatalogStore,
        evaluation: EvaluationRegistryStore,
        reporting: ReportingStore,
        store: LifecycleStore,
        *,
        clock=None,
    ) -> None:
        self.runs = runs
        self.catalog = catalog
        self.evaluation = evaluation
        self.reporting = reporting
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    def create_plan(self, request: dict) -> LifecyclePlan:
        adoption = self.reporting.get_adoption(request["adoption_id"])
        if adoption is None:
            raise LifecycleNotFound(request["adoption_id"])
        if adoption.decision != "ADOPTED":
            raise LifecycleConflict("ADOPTED済みの判断だけを運用計画にできます")
        experiment = self.catalog.get_experiment(request["experiment_id"])
        if experiment is None:
            raise LifecycleNotFound(request["experiment_id"])
        if experiment.definition.get("training_policy", "FIXED") != "MONTHLY_EXPANDING":
            raise LifecycleConflict("運用計画のexperimentはMONTHLY_EXPANDINGが必要です")
        snapshot = self.catalog.get_snapshot(experiment.snapshot_id)
        if snapshot is None:
            raise LifecycleNotFound(experiment.snapshot_id)
        if snapshot.manifest["selection_version"] != adoption.target["selection_version"]:
            raise LifecycleConflict("採用判断とexperimentのselection versionが一致しません")
        for run_id in (adoption.selected_run_id, adoption.fallback_run_id):
            run = self.runs.get_run(run_id)
            if run is None:
                raise LifecycleNotFound(run_id)
            if run.status != "SUCCEEDED":
                raise LifecycleConflict("初期championとfallbackは成功済みrunが必要です")
        plan, event = make_plan(
            request,
            adoption.selected_run_id,
            adoption.fallback_run_id,
            int(adoption.target["trial_period_days"]),
            now=self.clock(),
        )
        try:
            return self.store.put_plan(plan, event)
        except (ValueError, LifecycleStoreConflict) as exc:
            raise LifecycleConflict(str(exc)) from exc

    def get_plan(self, plan_id: str) -> LifecyclePlan:
        plan = self.store.get_plan(plan_id)
        if plan is None:
            raise LifecycleNotFound(plan_id)
        return plan

    def list_plans(self) -> list[LifecyclePlan]:
        return self.store.list_plans()

    def schedule(self) -> tuple[str, ...]:
        try:
            return enqueue_due_cycles(self.store, now=self.clock())
        except (ValueError, LifecycleStoreConflict) as exc:
            raise LifecycleConflict(str(exc)) from exc

    def list_cycles(self, plan_id: str) -> list[LifecycleCycle]:
        self.get_plan(plan_id)
        return self.store.list_cycles(plan_id)

    def complete_cycle(
        self, cycle_id: str, challenger_run_id: str, comparison_id: str
    ) -> LifecycleCycle:
        cycle = self._cycle(cycle_id)
        plan = self.get_plan(cycle.plan_id)
        if cycle.status != "QUEUED":
            if (
                cycle.challenger_run_id == challenger_run_id
                and cycle.comparison_id == comparison_id
            ):
                return cycle
            raise LifecycleConflict("解決済みcycleは変更できません")
        challenger = self.runs.get_run(challenger_run_id)
        if challenger is None:
            raise LifecycleNotFound(challenger_run_id)
        if challenger.status not in TERMINAL_STATUSES:
            raise LifecycleConflict("終端状態のchallenger runが必要です")
        if challenger.experiment_id != plan.experiment_id:
            raise LifecycleConflict("challenger runがplanのexperimentと一致しません")
        comparison = self.evaluation.get_comparison(comparison_id)
        if comparison is None:
            raise LifecycleNotFound(comparison_id)
        current = self._current_event(plan.plan_id)
        try:
            score = promotion_score(
                self.evaluation.list_run_evaluations(comparison_id),
                current.to_run_id,
                challenger_run_id,
                plan.minimum_improvement_pct,
                plan.maximum_failure_rate,
            )
        except ValueError as exc:
            raise LifecycleConflict(str(exc)) from exc
        status = "READY" if score["eligible"] else "REJECTED"
        resolved = replace(
            cycle,
            status=status,
            challenger_run_id=challenger_run_id,
            comparison_id=comparison_id,
            score=score,
            completed_at=self.clock().astimezone(UTC).isoformat(),
        )
        try:
            return self.store.resolve_cycle(resolved)
        except (ValueError, LifecycleStoreConflict) as exc:
            raise LifecycleConflict(str(exc)) from exc

    def fail_cycle(self, cycle_id: str, failure_code: str) -> LifecycleCycle:
        if not failure_code:
            raise ValueError("failure_codeは空にできません")
        cycle = self._cycle(cycle_id)
        if cycle.status != "QUEUED":
            raise LifecycleConflict("QUEUED cycleだけを失敗にできます")
        try:
            return self.store.resolve_cycle(
                replace(
                    cycle,
                    status="FAILED",
                    failure_code=failure_code,
                    completed_at=self.clock().astimezone(UTC).isoformat(),
                )
            )
        except (ValueError, LifecycleStoreConflict) as exc:
            raise LifecycleConflict(str(exc)) from exc

    def promote(self, cycle_id: str, expected_revision: int, approved_by: str, reason: str):
        cycle = self._cycle(cycle_id)
        if cycle.status != "READY" or not cycle.challenger_run_id:
            raise LifecycleConflict("READY cycleだけを昇格できます")
        plan = self.get_plan(cycle.plan_id)
        current = self._current_event(plan.plan_id)
        event = make_champion_event(
            plan,
            expected_revision + 1,
            "PROMOTED",
            current.to_run_id,
            cycle.challenger_run_id,
            cycle.cycle_id,
            cycle.comparison_id,
            approved_by,
            reason,
            now=self.clock(),
        )
        try:
            return self.store.append_champion_event(event, expected_revision, cycle.cycle_id)
        except LifecycleStoreConflict as exc:
            raise LifecycleConflict(str(exc)) from exc

    def rollback(
        self,
        plan_id: str,
        target_run_id: str,
        expected_revision: int,
        approved_by: str,
        reason: str,
    ):
        plan = self.get_plan(plan_id)
        events = self.store.list_champion_events(plan_id)
        current = events[-1]
        allowed = {plan.fallback_run_id, *(event.to_run_id for event in events[:-1])}
        if target_run_id not in allowed or target_run_id == current.to_run_id:
            raise LifecycleConflict("rollback先はfallbackまたは過去のchampionから選びます")
        event = make_champion_event(
            plan,
            expected_revision + 1,
            "ROLLED_BACK",
            current.to_run_id,
            target_run_id,
            None,
            None,
            approved_by,
            reason,
            now=self.clock(),
        )
        try:
            return self.store.append_champion_event(event, expected_revision)
        except LifecycleStoreConflict as exc:
            raise LifecycleConflict(str(exc)) from exc

    def status(self, plan_id: str) -> dict:
        plan = self.get_plan(plan_id)
        events = self.store.list_champion_events(plan_id)
        cycles = self.store.list_cycles(plan_id)
        forecasts = self.store.list_trial_forecasts(plan_id)
        assessments = self.store.list_trial_assessments(plan_id)
        return {
            "plan": asdict(plan),
            "champion": asdict(events[-1]),
            "cycles": [asdict(value) for value in cycles],
            "trial_forecast_count": len(forecasts),
            "latest_trial_assessment": None if not assessments else asdict(assessments[-1]),
        }

    def _cycle(self, cycle_id: str) -> LifecycleCycle:
        cycle = self.store.get_cycle(cycle_id)
        if cycle is None:
            raise LifecycleNotFound(cycle_id)
        return cycle

    def _current_event(self, plan_id: str):
        events = self.store.list_champion_events(plan_id)
        if not events:
            raise LifecycleNotFound(plan_id)
        return events[-1]
