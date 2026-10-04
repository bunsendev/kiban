"""Persistence mixin for formal change proposals and decision events."""

from __future__ import annotations

import json
from datetime import datetime

from .change_application_store import ChangeApplicationStoreMixin
from .contracts import FormalChangeDecision, FormalChangeTarget
from .domain import FieldLearningConflict
from .formal_change_domain import (
    FieldFormalChangeDecisionEvent,
    FieldFormalChangeProposal,
)


class FormalChangeStoreMixin(ChangeApplicationStoreMixin):
    def put_formal_change_proposal(self, value: FieldFormalChangeProposal):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT run_id FROM field_learning_experiment_runs "
                f"WHERE run_id=?{self.lock_clause}",
                (value.run_id,),
            ).fetchone() is None:
                raise KeyError(value.run_id)
            db.execute(
                "INSERT INTO field_formal_change_proposals VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(proposal_id) DO NOTHING",
                (
                    value.proposal_id, value.run_id, value.source_decision_revision,
                    value.change_target.value, _json(value.current_configuration),
                    _json(value.proposed_configuration), _json(value.application_scope),
                    _json(value.acceptance_criteria), _json(value.rollback_conditions),
                    value.rollback_target_version, value.author, value.known_at.isoformat(),
                    value.recorded_at.isoformat(), value.content_sha256, "NOT_APPLIED",
                ),
            )
        current = self.get_formal_change_proposal(value.proposal_id)
        if current is None or current.content_sha256 != value.content_sha256:
            raise ValueError("同じ正式変更案の内容は変更できません")
        return current

    def get_formal_change_proposal(self, proposal_id: str):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM field_formal_change_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        return None if row is None else _proposal(row)

    def list_formal_change_proposals(self, limit: int = 200):
        if not 1 <= limit <= 500:
            raise ValueError("limitは1以上500以下です")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_formal_change_proposals "
                "ORDER BY recorded_at DESC,proposal_id LIMIT ?", (limit,),
            ).fetchall()
        return [_proposal(row) for row in rows]

    def append_formal_change_decision(
        self, event: FieldFormalChangeDecisionEvent, expected_revision: int,
    ):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                f"SELECT proposal_id FROM field_formal_change_proposals "
                f"WHERE proposal_id=?{self.lock_clause}", (event.proposal_id,),
            ).fetchone() is None:
                raise KeyError(event.proposal_id)
            current = self._latest_revision(
                db, "field_formal_change_decision_events", event.proposal_id,
                id_column="proposal_id",
            )
            if current != expected_revision or event.revision != expected_revision + 1:
                raise FieldLearningConflict("ほかの利用者が先に正式変更案を判断しました")
            db.execute(
                "INSERT INTO field_formal_change_decision_events VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    event.decision_event_id, event.proposal_id, event.revision,
                    event.decision.value, event.approver, event.reason,
                    event.known_at.isoformat(), event.recorded_at.isoformat(),
                    event.content_sha256,
                ),
            )
        return event

    def list_formal_change_decisions(self, proposal_id: str):
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_formal_change_decision_events "
                "WHERE proposal_id=? ORDER BY revision", (proposal_id,),
            ).fetchall()
        return [_decision(row) for row in rows]


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _proposal(row):
    return FieldFormalChangeProposal(
        row["proposal_id"], row["run_id"], int(row["source_decision_revision"]),
        FormalChangeTarget(row["change_target"]),
        json.loads(row["current_configuration_json"]),
        json.loads(row["proposed_configuration_json"]),
        json.loads(row["application_scope_json"]),
        tuple(json.loads(row["acceptance_criteria_json"])),
        tuple(json.loads(row["rollback_conditions_json"])),
        row["rollback_target_version"], row["author"],
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])), row["content_sha256"],
    )


def _decision(row):
    return FieldFormalChangeDecisionEvent(
        row["decision_event_id"], row["proposal_id"], int(row["revision"]),
        FormalChangeDecision(row["decision"]), row["approver"], row["reason"],
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])), row["content_sha256"],
    )
