"""LifecycleのSQLite台帳と原子的な状態遷移。"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from .contracts import (
    ChampionEvent,
    LifecycleCycle,
    LifecyclePlan,
)
from .errors import LifecycleStoreConflict
from .records import (
    champion_event_from_row,
    champion_event_values,
    cycle_from_row,
    cycle_values,
    encode_json,
    plan_from_row,
    plan_values,
)
from .trial_store import TrialStoreMixin


class SqliteLifecycleStore(TrialStoreMixin):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    def put_plan(
        self, plan: LifecyclePlan, initial_event: ChampionEvent
    ) -> LifecyclePlan:
        if initial_event.plan_id != plan.plan_id or initial_event.action != "INITIALIZED":
            raise ValueError("初期champion eventがplanと一致しません")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO lifecycle_plans VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                plan_values(plan),
            )
            if db.execute(
                "SELECT plan_id FROM lifecycle_plans WHERE plan_id=?", (plan.plan_id,)
            ).fetchone() is None:
                raise LifecycleStoreConflict("同じplan版の内容は変更できません")
            db.execute(
                "INSERT INTO champion_events VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                champion_event_values(initial_event),
            )
        current = self.get_plan(plan.plan_id)
        events = self.list_champion_events(plan.plan_id)
        if (
            current is None
            or replace(current, created_at=plan.created_at) != plan
            or not events
            or replace(events[0], created_at=initial_event.created_at) != initial_event
        ):
            raise LifecycleStoreConflict("同じplan IDまたは版の内容は変更できません")
        return current

    def get_plan(self, plan_id: str) -> LifecyclePlan | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM lifecycle_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            return None if row is None else plan_from_row(row)

    def list_plans(self) -> list[LifecyclePlan]:
        with self._connect() as db:
            return [
                plan_from_row(row)
                for row in db.execute(
                    "SELECT * FROM lifecycle_plans ORDER BY created_at DESC,plan_id"
                )
            ]

    def put_cycle(self, cycle: LifecycleCycle) -> LifecycleCycle:
        if cycle.status != "QUEUED":
            raise ValueError("新規cycleはQUEUEDです")
        with self._connect() as db:
            db.execute(
                "INSERT INTO lifecycle_cycles VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                cycle_values(cycle),
            )
        current = self.get_cycle(cycle.cycle_id)
        if current is None or replace(current, created_at=cycle.created_at) != cycle:
            raise LifecycleStoreConflict("同じcycle月の内容は変更できません")
        return current

    def get_cycle(self, cycle_id: str) -> LifecycleCycle | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM lifecycle_cycles WHERE cycle_id=?", (cycle_id,)
            ).fetchone()
            return None if row is None else cycle_from_row(row)

    def list_cycles(self, plan_id: str) -> list[LifecycleCycle]:
        with self._connect() as db:
            return [
                cycle_from_row(row)
                for row in db.execute(
                    "SELECT * FROM lifecycle_cycles WHERE plan_id=? "
                    "ORDER BY scheduled_for,cycle_id",
                    (plan_id,),
                )
            ]

    def resolve_cycle(self, cycle: LifecycleCycle) -> LifecycleCycle:
        if cycle.status not in {"READY", "REJECTED", "FAILED"}:
            raise ValueError("cycle解決statusが不正です")
        current = self.get_cycle(cycle.cycle_id)
        if current is None:
            raise KeyError(cycle.cycle_id)
        if current.status != "QUEUED":
            if replace(current, completed_at=cycle.completed_at) == cycle:
                return current
            raise LifecycleStoreConflict("解決済みcycleは変更できません")
        if (
            current.plan_id != cycle.plan_id
            or current.due_month != cycle.due_month
            or current.scheduled_for != cycle.scheduled_for
            or current.created_at != cycle.created_at
        ):
            raise LifecycleStoreConflict("cycleの固定条件は変更できません")
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE lifecycle_cycles SET status=?,challenger_run_id=?,comparison_id=?,"
                "score_json=?,failure_code=?,completed_at=? "
                "WHERE cycle_id=? AND status='QUEUED'",
                (
                    cycle.status,
                    cycle.challenger_run_id,
                    cycle.comparison_id,
                    None if cycle.score is None else encode_json(cycle.score),
                    cycle.failure_code,
                    cycle.completed_at,
                    cycle.cycle_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LifecycleStoreConflict("cycleが同時に更新されました")
        return self.get_cycle(cycle.cycle_id)  # type: ignore[return-value]

    def append_champion_event(
        self,
        event: ChampionEvent,
        expected_revision: int,
        cycle_id: str | None = None,
    ) -> ChampionEvent:
        if cycle_id != event.cycle_id:
            raise LifecycleStoreConflict("eventと更新対象cycleが一致しません")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM champion_events WHERE plan_id=? "
                "ORDER BY revision DESC LIMIT 1",
                (event.plan_id,),
            ).fetchone()
            if row is None:
                raise KeyError(event.plan_id)
            current = champion_event_from_row(row)
            if current.revision != expected_revision:
                raise LifecycleStoreConflict("champion revisionが更新されています")
            if event.revision != expected_revision + 1 or event.from_run_id != current.to_run_id:
                raise LifecycleStoreConflict("champion状態遷移が不正です")
            if cycle_id is not None:
                cycle = db.execute(
                    "SELECT * FROM lifecycle_cycles WHERE cycle_id=? AND plan_id=?",
                    (cycle_id, event.plan_id),
                ).fetchone()
                if cycle is None or cycle["status"] != "READY":
                    raise LifecycleStoreConflict("昇格可能なcycleではありません")
            db.execute(
                "INSERT INTO champion_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                champion_event_values(event),
            )
            if cycle_id is not None:
                db.execute(
                    "UPDATE lifecycle_cycles SET status='PROMOTED' WHERE cycle_id=?",
                    (cycle_id,),
                )
        return event

    def list_champion_events(self, plan_id: str) -> list[ChampionEvent]:
        with self._connect() as db:
            return [
                champion_event_from_row(row)
                for row in db.execute(
                    "SELECT * FROM champion_events WHERE plan_id=? "
                    "ORDER BY revision,event_id",
                    (plan_id,),
                )
            ]

    def rows(self, table: str):
        allowed = {
            "lifecycle_plans",
            "lifecycle_cycles",
            "champion_events",
            "trial_forecast_records",
            "trial_assessments",
        }
        if table not in allowed:
            raise ValueError("tableが不正です")
        with self._connect() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]
