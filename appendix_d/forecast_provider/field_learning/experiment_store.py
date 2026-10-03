"""Persistence mixin for immutable learning experiments."""

from __future__ import annotations

import json
from datetime import datetime

from .contracts import LearningExperimentDecision, LearningExperimentTarget
from .domain import FieldLearningConflict
from .experiment_domain import (
    FieldLearningExperimentDecisionEvent,
    FieldLearningExperimentPlan,
    FieldLearningExperimentRun,
)


class ExperimentLearningStoreMixin:
    def put_experiment_plan(self, value: FieldLearningExperimentPlan):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO field_learning_experiment_plans VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(plan_id) DO NOTHING",
                (
                    value.plan_id, value.candidate_id, value.target.value,
                    value.baseline_version, value.challenger_version, value.hypothesis,
                    _json(value.evidence_case_ids), value.subject, value.known_at.isoformat(),
                    value.recorded_at.isoformat(), value.content_sha256,
                    len(value.evidence_case_ids),
                ),
            )
        current = self.get_experiment_plan(value.plan_id)
        if current is None or current.content_sha256 != value.content_sha256:
            raise ValueError("同じ調査計画の内容は変更できません")
        return current

    def get_experiment_plan(self, plan_id: str):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM field_learning_experiment_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
        return None if row is None else _plan(row)

    def list_experiment_plans(self, *, limit: int = 50):
        if not 1 <= limit <= 200:
            raise ValueError("limitは1以上200以下です")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_learning_experiment_plans "
                "ORDER BY recorded_at DESC,plan_id LIMIT ?", (limit,)
            ).fetchall()
        return [_plan(row) for row in rows]

    def put_experiment_run(self, value: FieldLearningExperimentRun):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT plan_id FROM field_learning_experiment_plans WHERE plan_id=?",
                (value.plan_id,),
            ).fetchone() is None:
                raise KeyError(value.plan_id)
            db.execute(
                "INSERT INTO field_learning_experiment_runs VALUES "
                "(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO NOTHING",
                (
                    value.run_id, value.plan_id, value.result_version, value.source_sha256,
                    _json(value.report), value.subject, value.known_at.isoformat(),
                    value.recorded_at.isoformat(), value.content_sha256,
                    int(value.report["coverage"]["comparable_count"]),
                ),
            )
        current = self.get_experiment_run(value.run_id)
        if current is None or current.content_sha256 != value.content_sha256:
            raise ValueError("同じ比較runの内容は変更できません")
        return current

    def get_experiment_run(self, run_id: str):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM field_learning_experiment_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return None if row is None else _run(row)

    def list_experiment_runs(self, plan_id: str):
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_learning_experiment_runs WHERE plan_id=? "
                "ORDER BY recorded_at DESC,run_id", (plan_id,)
            ).fetchall()
        return [_run(row) for row in rows]

    def append_experiment_decision(
        self, event: FieldLearningExperimentDecisionEvent, expected_revision: int,
    ):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                f"SELECT run_id FROM field_learning_experiment_runs "
                f"WHERE run_id=?{self.lock_clause}", (event.run_id,),
            ).fetchone() is None:
                raise KeyError(event.run_id)
            current = self._latest_revision(
                db, "field_learning_experiment_decision_events", event.run_id,
                id_column="run_id",
            )
            if current != expected_revision or event.revision != expected_revision + 1:
                raise FieldLearningConflict("ほかの利用者が先に比較runを判断しました")
            db.execute(
                "INSERT INTO field_learning_experiment_decision_events "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    event.decision_event_id, event.run_id, event.revision,
                    event.decision.value, event.subject, event.reason,
                    event.known_at.isoformat(), event.recorded_at.isoformat(),
                    event.content_sha256,
                ),
            )
        return event

    def list_experiment_decisions(self, run_id: str):
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_learning_experiment_decision_events "
                "WHERE run_id=? ORDER BY revision", (run_id,)
            ).fetchall()
        return [_decision(row) for row in rows]


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _plan(row):
    return FieldLearningExperimentPlan(
        row["plan_id"], row["candidate_id"], LearningExperimentTarget(row["target"]),
        row["baseline_version"], row["challenger_version"], row["hypothesis"],
        tuple(json.loads(row["evidence_case_ids_json"])), row["subject"],
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])), row["content_sha256"],
    )


def _run(row):
    return FieldLearningExperimentRun(
        row["run_id"], row["plan_id"], row["result_version"], row["source_sha256"],
        json.loads(row["report_json"]), row["subject"],
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])), row["content_sha256"],
    )


def _decision(row):
    return FieldLearningExperimentDecisionEvent(
        row["decision_event_id"], row["run_id"], int(row["revision"]),
        LearningExperimentDecision(row["decision"]), row["subject"], row["reason"],
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])), row["content_sha256"],
    )
