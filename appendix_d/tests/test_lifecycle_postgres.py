"""Lifecycle台帳のPostgreSQL互換試験。"""

import os
import uuid
from datetime import UTC, date, datetime

import pytest

from forecast_provider.lifecycle import PostgresLifecycleStore
from forecast_provider.lifecycle.plan_domain import make_plan
from forecast_provider.lifecycle.scheduler import enqueue_due_cycles


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_lifecycle_plan_and_scheduler_are_idempotent():
    store = PostgresLifecycleStore(os.environ["KIBAN_TEST_POSTGRES_DSN"])
    suffix = uuid.uuid4().hex
    definition = {
        "plan_version": f"postgres-{suffix}",
        "adoption_id": f"adoption-{suffix}",
        "experiment_id": f"experiment-{suffix}",
        "schedule_day": 1,
        "schedule_time": "02:00",
        "timezone": "Asia/Tokyo",
        "trial_start_date": date(2026, 1, 1),
        "metric": "wape_pct",
        "minimum_improvement_pct": 0.0,
        "maximum_failure_rate": 0.0,
        "created_by": "postgres-test",
        "reason": "PostgreSQL互換試験",
    }
    now = datetime(2026, 2, 15, tzinfo=UTC)
    plan, initial = make_plan(
        definition, f"champion-{suffix}", f"fallback-{suffix}", 60, now=now
    )
    try:
        store.put_plan(plan, initial)
        first = enqueue_due_cycles(store, now=now)
        second = enqueue_due_cycles(store, now=now)
        assert first == second
        assert len(store.list_cycles(plan.plan_id)) == 2
    finally:
        with store._raw_connect() as db:
            db.execute("DELETE FROM lifecycle_cycles WHERE plan_id=%s", (plan.plan_id,))
            db.execute("DELETE FROM champion_events WHERE plan_id=%s", (plan.plan_id,))
            db.execute("DELETE FROM lifecycle_plans WHERE plan_id=%s", (plan.plan_id,))
