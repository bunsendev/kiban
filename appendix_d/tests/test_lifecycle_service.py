"""Phase 1S lifecycleサービスの昇格、rollback、将来trial境界。"""

from datetime import UTC, date, datetime, timedelta

import pytest

from forecast_provider.catalog import ExperimentRecord, SnapshotRecord
from forecast_provider.evaluation_registry import ComparisonRecord, RunEvaluation
from forecast_provider.jobs import RunSnapshot
from forecast_provider.lifecycle import (
    LifecycleConflict,
    LifecycleService,
    SqliteLifecycleStore,
    TrialLifecycleService,
)
from forecast_provider.reporting import AdoptionRecord


class Records:
    def __init__(self, values):
        self.values = values

    def get_adoption(self, identifier):
        return self.values.get(identifier)


class Runs:
    def __init__(self, values, results=None):
        self.values = values
        self.results = results or {}

    def get_run(self, identifier):
        return self.values.get(identifier)

    def get_run_results(self, identifier):
        return self.results.get(identifier)


class Catalog:
    def __init__(self, experiments, snapshots):
        self.experiments = experiments
        self.snapshots = snapshots

    def get_experiment(self, identifier):
        return self.experiments.get(identifier)

    def get_snapshot(self, identifier):
        return self.snapshots.get(identifier)


class Evaluations:
    def __init__(self, comparisons, scores):
        self.comparisons = comparisons
        self.scores = scores

    def get_comparison(self, identifier):
        return self.comparisons.get(identifier)

    def list_run_evaluations(self, identifier):
        return self.scores.get(identifier, [])


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def _snapshot():
    return SnapshotRecord("snapshot-1", 1, "hash", {"selection_version": "selection-v1"})


def _experiment(identifier, policy):
    definition = {
        "provider_id": "builtin-baseline",
        "model_name": "moving_average_28",
        "params": {},
        "preprocessing_version": "daily-v1",
        "training_policy": policy,
    }
    return ExperimentRecord(identifier, 1, f"fingerprint-{identifier}", "snapshot-1", definition)


def _run(identifier, experiment):
    return RunSnapshot(
        identifier, experiment, f"fingerprint-{identifier}", "SUCCEEDED", False, {}, 0
    )


def fixture(tmp_path, *, now=datetime(2026, 3, 15, tzinfo=UTC)):
    runs = Runs(
        {
            "champion": _run("champion", "fixed"),
            "fallback": _run("fallback", "fixed"),
            "challenger": _run("challenger", "monthly"),
        }
    )
    catalog = Catalog(
        {
            "fixed": _experiment("fixed", "FIXED"),
            "monthly": _experiment("monthly", "MONTHLY_EXPANDING"),
        },
        {"snapshot-1": _snapshot()},
    )
    adoption = AdoptionRecord(
        "adoption-1",
        1,
        "adoption-fingerprint",
        "adoption-v1",
        "comparison-adoption",
        "acceptance-1",
        "ADOPTED",
        "champion",
        "fallback",
        {
            "selection_version": "selection-v1",
            "canonical_product_ids": ["P1"],
            "center_ids": ["C1"],
            "trial_period_days": 90,
        },
        "owner",
        "採用",
        now.isoformat(),
    )
    comparison = ComparisonRecord(
        "comparison-cycle", 1, "comparison-fingerprint", {}, {}, now.isoformat()
    )
    scores = [
        RunEvaluation(
            "comparison-cycle",
            "champion",
            "builtin-baseline",
            "moving_average_28",
            "c1",
            {"common_metrics": {"wape_pct": 10}, "run_success_rate": 1},
        ),
        RunEvaluation(
            "comparison-cycle",
            "challenger",
            "builtin-baseline",
            "moving_average_28",
            "c2",
            {"common_metrics": {"wape_pct": 8}, "run_success_rate": 1},
        ),
    ]
    evaluations = Evaluations({"comparison-cycle": comparison}, {"comparison-cycle": scores})
    store = SqliteLifecycleStore(tmp_path / "lifecycle.sqlite3")
    clock = Clock(now)
    service = LifecycleService(
        runs, catalog, evaluations, Records({"adoption-1": adoption}), store, clock=clock
    )
    request = {
        "plan_version": "lifecycle-v1",
        "adoption_id": "adoption-1",
        "experiment_id": "monthly",
        "schedule_day": 1,
        "schedule_time": "02:00",
        "timezone": "Asia/Tokyo",
        "trial_start_date": date(2026, 1, 1),
        "metric": "wape_pct",
        "minimum_improvement_pct": 2.0,
        "maximum_failure_rate": 0.0,
        "created_by": "approver",
        "reason": "運用開始",
    }
    return service, store, runs, catalog, evaluations, clock, request


def test_service_promotes_eligible_challenger_and_rolls_back(tmp_path):
    service, _, _, _, _, _, request = fixture(tmp_path)
    plan = service.create_plan(request)
    cycle_id = service.schedule()[0]
    cycle = service.complete_cycle(cycle_id, "challenger", "comparison-cycle")

    assert cycle.status == "READY"
    promoted = service.promote(cycle_id, 1, "approver", "20%改善")
    assert promoted.revision == 2 and promoted.to_run_id == "challenger"
    with pytest.raises(LifecycleConflict, match="revision"):
        service.rollback(plan.plan_id, "fallback", 1, "approver", "古いrevision")
    rolled_back = service.rollback(plan.plan_id, "fallback", 2, "approver", "障害対応")
    assert rolled_back.revision == 3 and rolled_back.to_run_id == "fallback"
    assert service.status(plan.plan_id)["champion"]["action"] == "ROLLED_BACK"


def test_service_rejects_fixed_training_plan(tmp_path):
    service, _, _, _, _, _, request = fixture(tmp_path)
    request["experiment_id"] = "fixed"
    with pytest.raises(LifecycleConflict, match="MONTHLY_EXPANDING"):
        service.create_plan(request)


def test_trial_requires_pre_truth_record_and_complete_future_coverage(tmp_path):
    early = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    service, store, runs, catalog, evaluations, clock, request = fixture(tmp_path, now=early)
    plan = service.create_plan(request)
    origin = date(2026, 1, 1)
    runs.values["trial"] = _run("trial", "fixed")
    runs.results["trial"] = {
        "origins": [{"origin_date": origin, "status": "SUCCEEDED"}],
        "values": [
            {"origin_date": origin, "target_date": origin + timedelta(days=offset)}
            for offset in range(1, 31)
        ],
        "failures": [],
    }
    trial = TrialLifecycleService(runs, catalog, evaluations, store, clock=clock)

    recorded = trial.record_forecast(plan.plan_id, "trial", origin, "analyst")
    assert recorded.origin_date == origin

    comparison = ComparisonRecord(
        "trial-comparison",
        1,
        "trial-fingerprint",
        {"purpose": "FUTURE_TRIAL"},
        {},
        early.isoformat(),
    )
    evaluations.comparisons["trial-comparison"] = comparison
    evaluations.scores["trial-comparison"] = [
        RunEvaluation("trial-comparison", "trial", "p", "m", "c", {})
    ]
    clock.value = datetime(2026, 2, 2, tzinfo=UTC)
    assessment = trial.assess(
        plan.plan_id,
        0,
        date(2026, 1, 2),
        date(2026, 1, 31),
        "trial-comparison",
        "COMPLETE",
        "approver",
        "30日確認",
    )
    assert assessment.evidence_kind == "FUTURE_TRIAL"
    with pytest.raises(LifecycleConflict, match="利用可能"):
        trial.record_forecast(plan.plan_id, "trial", origin, "analyst")
