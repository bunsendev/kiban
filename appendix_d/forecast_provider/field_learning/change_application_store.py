"""Persistence mixin for audited Pilot change applications."""

from __future__ import annotations

import json
from datetime import datetime

from .change_application_domain import (
    FieldChangeApplication,
    FieldChangeApplicationEvent,
)
from .contracts import ChangeApplicationState, ChangeApplicationTransition
from .domain import FieldLearningConflict
from .runtime_assignment_store import RuntimeAssignmentStoreMixin


class ChangeApplicationStoreMixin(RuntimeAssignmentStoreMixin):
    def put_change_application(self, value: FieldChangeApplication):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT proposal_id FROM field_formal_change_proposals "
                f"WHERE proposal_id=?{self.lock_clause}", (value.proposal_id,),
            ).fetchone() is None:
                raise KeyError(value.proposal_id)
            db.execute(
                "INSERT INTO field_change_applications VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(application_id) DO NOTHING",
                (
                    value.application_id, value.proposal_id,
                    value.source_proposal_decision_revision, value.candidate_version,
                    _json(value.application_scope), value.backup_reference,
                    value.backup_sha256, value.executor, value.known_at.isoformat(),
                    value.recorded_at.isoformat(), value.content_sha256,
                ),
            )
        current = self.get_change_application(value.application_id)
        if current is None or current.content_sha256 != value.content_sha256:
            raise ValueError("同じPilot適用計画の内容は変更できません")
        return current

    def get_change_application(self, application_id: str):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM field_change_applications WHERE application_id=?",
                (application_id,),
            ).fetchone()
        return None if row is None else _application(row)

    def list_change_applications(self, limit: int = 200):
        if not 1 <= limit <= 500:
            raise ValueError("limitは1以上500以下です")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_change_applications "
                "ORDER BY recorded_at DESC,application_id LIMIT ?", (limit,),
            ).fetchall()
        return [_application(row) for row in rows]

    def append_change_application_event(
        self, event: FieldChangeApplicationEvent, expected_revision: int,
    ):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT application_id FROM field_change_applications "
                f"WHERE application_id=?{self.lock_clause}", (event.application_id,),
            ).fetchone() is None:
                raise KeyError(event.application_id)
            current = self._latest_revision(
                db, "field_change_application_events", event.application_id,
                id_column="application_id",
            )
            if current != expected_revision or event.revision != expected_revision + 1:
                raise FieldLearningConflict("ほかの利用者が先にPilot適用状態を更新しました")
            db.execute(
                "INSERT INTO field_change_application_events VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event.event_id, event.application_id, event.revision,
                    event.transition.value, event.resulting_state.value,
                    event.actor, event.reason, _json(event.evidence),
                    event.known_at.isoformat(), event.recorded_at.isoformat(),
                    event.content_sha256,
                ),
            )
        return event

    def list_change_application_events(self, application_id: str):
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_change_application_events "
                "WHERE application_id=? ORDER BY revision", (application_id,),
            ).fetchall()
        return [_event(row) for row in rows]


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _application(row):
    return FieldChangeApplication(
        row["application_id"], row["proposal_id"],
        int(row["source_proposal_decision_revision"]), row["candidate_version"],
        json.loads(row["application_scope_json"]), row["backup_reference"],
        row["backup_sha256"], row["executor"],
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])), row["content_sha256"],
    )


def _event(row):
    return FieldChangeApplicationEvent(
        row["event_id"], row["application_id"], int(row["revision"]),
        ChangeApplicationTransition(row["transition"]),
        ChangeApplicationState(row["resulting_state"]), row["actor"], row["reason"],
        json.loads(row["evidence_json"]),
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])), row["content_sha256"],
    )
