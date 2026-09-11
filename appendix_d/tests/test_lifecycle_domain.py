"""Phase 1S lifecycle台帳の監査履歴と排他制御。"""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from forecast_provider.lifecycle.domain import (
    due_schedules,
    make_champion_event,
)
from forecast_provider.lifecycle.plan_domain import make_plan
from forecast_provider.lifecycle.promotion import promotion_score
from forecast_provider.lifecycle.scheduler import enqueue_due_cycles
from forecast_provider.lifecycle.store import LifecycleStoreConflict, SqliteLifecycleStore

NOW = datetime(2026, 3, 15, 0, 0, tzinfo=UTC)


def plan_definition():
    return {
        "plan_version": "lifecycle-v1",
        "adoption_id": "adoption-1",
        "experiment_id": "experiment-monthly",
        "schedule_day": 1,
        "schedule_time": "02:00",
        "timezone": "Asia/Tokyo",
        "trial_start_date": date(2026, 1, 1),
        "metric": "wape_pct",
        "minimum_improvement_pct": 2.0,
        "maximum_failure_rate": 0.0,
        "created_by": "approver@example.test",
        "reason": "継続学習を開始",
    }


def saved_plan(tmp_path):
    store = SqliteLifecycleStore(tmp_path / "lifecycle.sqlite3")
    plan, initial = make_plan(plan_definition(), "champion-1", "fallback-1", 90, now=NOW)
    return store, store.put_plan(plan, initial)


def test_scheduler_is_idempotent_and_respects_trial_window(tmp_path):
    store, plan = saved_plan(tmp_path)

    expected = due_schedules(plan, NOW)
    first = enqueue_due_cycles(store, now=NOW)
    second = enqueue_due_cycles(store, now=NOW)

    assert [month for month, _ in expected] == ["2026-01", "2026-02", "2026-03"]
    assert first == second
    assert len(store.list_cycles(plan.plan_id)) == 3


def test_champion_events_are_append_only_and_revision_guarded(tmp_path):
    store, plan = saved_plan(tmp_path)
    cycle_id = enqueue_due_cycles(store, now=NOW)[0]
    cycle = store.get_cycle(cycle_id)
    ready = replace(
        cycle,
        status="READY",
        challenger_run_id="challenger-1",
        comparison_id="comparison-1",
        score={"eligible": True},
        completed_at=NOW.isoformat(),
    )
    store.resolve_cycle(ready)
    event = make_champion_event(
        plan,
        2,
        "PROMOTED",
        "champion-1",
        "challenger-1",
        cycle_id,
        "comparison-1",
        "approver@example.test",
        "基準を満たした",
        now=NOW,
    )

    store.append_champion_event(event, 1, cycle_id)

    assert store.get_cycle(cycle_id).status == "PROMOTED"
    assert [value.to_run_id for value in store.list_champion_events(plan.plan_id)] == [
        "champion-1",
        "challenger-1",
    ]
    with pytest.raises(LifecycleStoreConflict):
        store.append_champion_event(
            replace(event, event_id="another", revision=3, from_run_id="challenger-1"),
            1,
        )


def test_plan_requires_at_least_30_trial_days():
    with pytest.raises(ValueError, match="30"):
        make_plan(plan_definition(), "champion", "fallback", 29, now=NOW)


def test_non_finite_promotion_evidence_is_rejected_without_persisting_nan():
    class Evaluation:
        def __init__(self, run_id, score):
            self.run_id = run_id
            self.score = score

    result = promotion_score(
        [
            Evaluation("champion", {"common_metrics": {"wape_pct": 10.0}}),
            Evaluation(
                "challenger",
                {"common_metrics": {"wape_pct": float("nan")}, "run_success_rate": 1.0},
            ),
        ],
        "champion",
        "challenger",
        1.0,
        0.0,
    )

    assert result["eligible"] is False
    assert result["challenger_value"] is None
    assert result["reason"] == "COMMON_METRIC_OR_SUCCESS_RATE_INVALID"
