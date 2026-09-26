"""版付きsnapshot時刻policyの永続化mixin。"""

from __future__ import annotations

from datetime import time

from .contracts import SnapshotAtSourceKind
from .domain import canonical_datetime
from .job_store import _datetime
from .snapshot_time import SnapshotTimePolicy


class SnapshotTimePolicyStoreMixin:
    def put_snapshot_time_policy(self, value: SnapshotTimePolicy) -> None:
        expected = _values(value)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM inventory_snapshot_time_policies WHERE policy_version=?",
                (value.policy_version,),
            ).fetchone()
            if row is not None:
                actual = tuple(row[name] for name in _COLUMNS)
                if actual == expected:
                    return
                raise ValueError("同じsnapshot time policy versionの内容は変更できません")
            db.execute(
                "INSERT INTO inventory_snapshot_time_policies VALUES (?,?,?,?,?,?,?,?)",
                expected,
            )

    def get_snapshot_time_policy(self, policy_version: str) -> SnapshotTimePolicy | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM inventory_snapshot_time_policies WHERE policy_version=?",
                (policy_version,),
            ).fetchone()
        if row is None:
            return None
        return SnapshotTimePolicy(
            row["policy_version"],
            row["content_sha256"],
            SnapshotAtSourceKind(row["source_kind"]),
            time.fromisoformat(row["cutoff_time"]),
            row["timezone_name"],
            row["created_by"],
            row["reason"],
            _datetime(row["created_at"]),
        )


_COLUMNS = (
    "policy_version",
    "content_sha256",
    "source_kind",
    "cutoff_time",
    "timezone_name",
    "created_by",
    "reason",
    "created_at",
)


def _values(value: SnapshotTimePolicy) -> tuple:
    return (
        value.policy_version,
        value.content_sha256,
        value.source_kind.value,
        value.cutoff_time.isoformat(),
        value.timezone_name,
        value.created_by,
        value.reason,
        canonical_datetime(value.created_at, "created_at"),
    )
