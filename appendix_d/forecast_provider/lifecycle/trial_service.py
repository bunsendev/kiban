"""将来実績を使う前に予測を固定し、30日以上のtrialを評価する。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from ..catalog import CatalogStore
from ..evaluation_registry.contracts import EvaluationRegistryStore
from ..jobs.contracts import RunStore
from ..run_context import cutoff_for_origin
from .contracts import LifecycleStore
from .domain import make_trial_assessment, make_trial_forecast
from .service import LifecycleConflict, LifecycleNotFound
from .store import LifecycleStoreConflict


class TrialLifecycleService:
    def __init__(
        self,
        runs: RunStore,
        catalog: CatalogStore,
        evaluation: EvaluationRegistryStore,
        store: LifecycleStore,
        *,
        clock=None,
    ) -> None:
        self.runs = runs
        self.catalog = catalog
        self.evaluation = evaluation
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    def record_forecast(self, plan_id: str, run_id: str, origin: date, actor: str):
        plan = self._plan(plan_id)
        run = self.runs.get_run(run_id)
        if run is None:
            raise LifecycleNotFound(run_id)
        results = self.runs.get_run_results(run_id)
        if results is None or not any(
            value["origin_date"] == origin and value["status"] == "SUCCEEDED"
            for value in results["origins"]
        ):
            raise LifecycleConflict("成功済みのtrial originが必要です")
        now = self.clock()
        truth_deadline = cutoff_for_origin(origin + timedelta(days=1))
        if now > truth_deadline:
            raise LifecycleConflict("最初の将来実績が利用可能になった後は記録できません")
        current = self.store.list_champion_events(plan_id)
        if not current:
            raise LifecycleNotFound(plan_id)
        if not self._same_model_contract(run_id, current[-1].to_run_id):
            raise LifecycleConflict("trial runが現在championのモデル条件と一致しません")
        value = make_trial_forecast(plan, run_id, origin, actor, now=now)
        try:
            return self.store.put_trial_forecast(value)
        except LifecycleStoreConflict as exc:
            raise LifecycleConflict(str(exc)) from exc

    def assess(
        self,
        plan_id: str,
        expected_revision: int,
        period_start: date,
        period_end: date,
        comparison_id: str,
        decision: str,
        actor: str,
        reason: str,
    ):
        plan = self._plan(plan_id)
        now = self.clock()
        if now < cutoff_for_origin(period_end):
            raise LifecycleConflict("評価期間末日の実績がまだ利用可能ではありません")
        comparison = self.evaluation.get_comparison(comparison_id)
        if comparison is None:
            raise LifecycleNotFound(comparison_id)
        if comparison.definition.get("purpose") != "FUTURE_TRIAL":
            raise LifecycleConflict("trial評価にはpurpose=FUTURE_TRIALの比較が必要です")
        records = [
            value
            for value in self.store.list_trial_forecasts(plan_id)
            if value.origin_date <= period_end
        ]
        if not records:
            raise LifecycleConflict("trial予測の事前記録がありません")
        compared = {
            value.run_id
            for value in self.evaluation.list_run_evaluations(comparison_id)
        }
        recorded_runs = {value.run_id for value in records}
        if not recorded_runs.issubset(compared):
            raise LifecycleConflict("比較にtrial記録済みrunが含まれません")
        self._validate_target_coverage(records, period_start, period_end)
        value = make_trial_assessment(
            plan,
            expected_revision + 1,
            period_start,
            period_end,
            comparison_id,
            decision,
            actor,
            reason,
            now=now,
        )
        try:
            return self.store.append_trial_assessment(value, expected_revision)
        except LifecycleStoreConflict as exc:
            raise LifecycleConflict(str(exc)) from exc

    def list_forecasts(self, plan_id: str):
        self._plan(plan_id)
        return self.store.list_trial_forecasts(plan_id)

    def list_assessments(self, plan_id: str):
        self._plan(plan_id)
        return self.store.list_trial_assessments(plan_id)

    def _plan(self, plan_id: str):
        plan = self.store.get_plan(plan_id)
        if plan is None:
            raise LifecycleNotFound(plan_id)
        return plan

    def _same_model_contract(self, first_run_id: str, second_run_id: str) -> bool:
        first = self.runs.get_run(first_run_id)
        second = self.runs.get_run(second_run_id)
        if first is None or second is None:
            return False
        first_experiment = self.catalog.get_experiment(first.experiment_id)
        second_experiment = self.catalog.get_experiment(second.experiment_id)
        if first_experiment is None or second_experiment is None:
            return False
        keys = ("provider_id", "model_name", "params", "preprocessing_version")
        if any(
            first_experiment.definition.get(key) != second_experiment.definition.get(key)
            for key in keys
        ):
            return False
        first_snapshot = self.catalog.get_snapshot(first_experiment.snapshot_id)
        second_snapshot = self.catalog.get_snapshot(second_experiment.snapshot_id)
        return bool(
            first_snapshot
            and second_snapshot
            and first_snapshot.manifest["selection_version"]
            == second_snapshot.manifest["selection_version"]
        )

    def _validate_target_coverage(self, records, start: date, end: date) -> None:
        covered = set()
        for record in records:
            results = self.runs.get_run_results(record.run_id)
            if results is None:
                continue
            covered.update(
                value["target_date"]
                for value in results["values"]
                if value["origin_date"] == record.origin_date
            )
        expected = {
            start + timedelta(days=offset) for offset in range((end - start).days + 1)
        }
        if not expected.issubset(covered):
            raise LifecycleConflict("trial期間の予測対象日が完全に記録されていません")
