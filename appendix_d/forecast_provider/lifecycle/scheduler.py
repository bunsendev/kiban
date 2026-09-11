"""期限到来した月次retraining cycleを冪等に登録する。"""

from __future__ import annotations

from datetime import UTC, datetime

from .contracts import LifecycleStore
from .domain import due_schedules, make_cycle


def enqueue_due_cycles(
    store: LifecycleStore, *, now: datetime | None = None
) -> tuple[str, ...]:
    current = datetime.now(UTC) if now is None else now
    if current.tzinfo is None:
        raise ValueError("scheduler時刻はtimezone付きです")
    identifiers = []
    for plan in store.list_plans():
        for due_month, scheduled_for in due_schedules(plan, current):
            cycle = make_cycle(plan, due_month, scheduled_for, now=current)
            identifiers.append(store.put_cycle(cycle).cycle_id)
    return tuple(identifiers)

