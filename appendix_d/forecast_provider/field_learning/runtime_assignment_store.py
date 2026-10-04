"""Append-only persistence for runtime assignment resolution evidence."""

from __future__ import annotations

import json
from datetime import datetime

from .contracts import RuntimeAssignmentStatus
from .runtime_assignment_domain import FieldRuntimeAssignmentResolution


class RuntimeAssignmentStoreMixin:
    def put_runtime_assignment_resolution(self, value: FieldRuntimeAssignmentResolution):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO field_runtime_assignment_resolutions VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(resolution_id) DO NOTHING",
                (
                    value.resolution_id, value.execution_key, value.pilot_scope_version,
                    value.status.value, value.selected_version,
                    _json(value.selected_configuration), value.application_id,
                    value.application_revision, value.proposal_id,
                    value.candidate_manifest_sha256, value.reason_code, value.actor,
                    value.known_at.isoformat(), value.recorded_at.isoformat(),
                    value.content_sha256,
                ),
            )
        current = self.get_runtime_assignment_resolution(value.resolution_id)
        if current is None or current.content_sha256 != value.content_sha256:
            raise ValueError("同じ実行時選択証跡の内容は変更できません")
        return current

    def get_runtime_assignment_resolution(self, resolution_id: str):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM field_runtime_assignment_resolutions WHERE resolution_id=?",
                (resolution_id,),
            ).fetchone()
        return None if row is None else _resolution(row)

    def list_runtime_assignment_resolutions(
        self, *, execution_key: str | None = None, limit: int = 500,
    ):
        if not 1 <= limit <= 1000:
            raise ValueError("limitは1以上1000以下です")
        where = " WHERE execution_key=?" if execution_key else ""
        params = (execution_key, limit) if execution_key else (limit,)
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_runtime_assignment_resolutions" + where
                + " ORDER BY recorded_at DESC,resolution_id LIMIT ?", params,
            ).fetchall()
        return [_resolution(row) for row in rows]


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _resolution(row):
    return FieldRuntimeAssignmentResolution(
        row["resolution_id"], row["execution_key"], row["pilot_scope_version"],
        RuntimeAssignmentStatus(row["status"]), row["selected_version"],
        json.loads(row["selected_configuration_json"]), row["application_id"],
        None if row["application_revision"] is None else int(row["application_revision"]),
        row["proposal_id"], row["candidate_manifest_sha256"], row["reason_code"],
        row["actor"], datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])), row["content_sha256"],
    )
