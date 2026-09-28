"""候補・版付き認識契約・承認履歴のローカル永続化。原本行は保存しない。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .inbox_policy import SchemaRule
from .learning_candidate import LearningCandidate

SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_candidates (
 candidate_id TEXT PRIMARY KEY,
 policy_version TEXT NOT NULL,
 header_sha256 TEXT NOT NULL,
 structure_json TEXT NOT NULL,
 archive_reference TEXT NOT NULL,
 status TEXT NOT NULL,
 confirmed_kind TEXT,
 learning_version TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_contracts (
 learning_version TEXT PRIMARY KEY,
 candidate_id TEXT NOT NULL,
 rule_json TEXT NOT NULL,
 source_unit TEXT,
 normalized_unit TEXT,
 supersedes_version TEXT,
 status TEXT NOT NULL,
 approved_by TEXT NOT NULL,
 approved_at TEXT NOT NULL,
 FOREIGN KEY(candidate_id) REFERENCES learning_candidates(candidate_id)
);
CREATE TABLE IF NOT EXISTS learning_events (
 event_id TEXT PRIMARY KEY,
 candidate_id TEXT NOT NULL,
 action TEXT NOT NULL,
 actor TEXT NOT NULL,
 before_status TEXT NOT NULL,
 after_status TEXT NOT NULL,
 recorded_at TEXT NOT NULL
);
"""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class LearningStore:
    def __init__(self, path: Path):
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("LEARNING_STORE_PATH_INVALID")
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_candidate(
        self, candidate: LearningCandidate, policy_version: str, archive_reference: str,
    ) -> str:
        candidate_id = hashlib.sha256(
            _json([policy_version, candidate.header_sha256, candidate.suggested_kind]).encode()
        ).hexdigest()
        with self._connect() as db:
            db.execute(
                "INSERT INTO learning_candidates VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(candidate_id) DO NOTHING",
                (candidate_id, policy_version, candidate.header_sha256,
                 _json(asdict(candidate)), archive_reference, "PENDING_OPERATOR",
                 None, None, datetime.now(UTC).isoformat()),
            )
            db.execute(
                "UPDATE learning_candidates SET status='PENDING_OPERATOR',"
                "confirmed_kind=NULL,learning_version=NULL,archive_reference=? "
                "WHERE candidate_id=? AND status='INACTIVE'",
                (archive_reference, candidate_id),
            )
        return candidate_id

    def get_candidate(self, candidate_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM learning_candidates WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
        return (
            None if row is None else
            {**dict(row), "structure": json.loads(row["structure_json"])}
        )

    def list_candidates(self) -> list[dict]:
        with self._connect() as db:
            ids = [row[0] for row in db.execute(
                "SELECT candidate_id FROM learning_candidates "
                "ORDER BY created_at DESC,candidate_id DESC LIMIT 100"
            )]
        return [item for value in ids if (item := self.get_candidate(value))]

    def decide(
        self, candidate_id: str, *, actor: str, action: str, kind: str,
        rule: SchemaRule | None = None, source_unit: str | None = None,
        normalized_unit: str | None = None,
    ) -> dict:
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM learning_candidates WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise ValueError("LEARNING_CANDIDATE_NOT_FOUND")
            if row["status"] != "PENDING_OPERATOR" and action in {"OPERATOR_CONFIRM", "DISAGREE"}:
                if row["confirmed_kind"] == kind:
                    return self.get_candidate(candidate_id) or {}
                raise ValueError("LEARNING_ALREADY_DECIDED")
            if row["status"] != "PENDING_ADMIN" and action == "ADMIN_APPROVE":
                if row["status"] == "ACTIVE" and row["confirmed_kind"] == kind:
                    return self.get_candidate(candidate_id) or {}
                raise ValueError("LEARNING_ADMIN_DECISION_INVALID")
            if action == "ADMIN_REJECT" and row["status"] != "PENDING_ADMIN":
                raise ValueError("LEARNING_ADMIN_DECISION_INVALID")
            if action not in {"OPERATOR_CONFIRM", "DISAGREE", "ADMIN_APPROVE", "ADMIN_REJECT"}:
                raise ValueError("LEARNING_ACTION_INVALID")
            target = (
                "ACTIVE" if rule is not None else
                "REJECTED" if action == "ADMIN_REJECT" else "PENDING_ADMIN"
            )
            version = None
            if rule is not None:
                prior_rows = db.execute(
                    "SELECT learning_version,rule_json FROM learning_contracts "
                    "ORDER BY approved_at DESC,learning_version DESC"
                ).fetchall()
                parent_schema = json.loads(row["structure_json"]).get("parent_schema_id")
                supersedes = next(
                    (old["learning_version"] for old in prior_rows
                     if json.loads(old["rule_json"])["schema_id"] == parent_schema),
                    None,
                )
                previous_same = next(
                    (old["learning_version"] for old in prior_rows
                     if json.loads(old["rule_json"])["schema_id"] == rule.schema_id),
                    None,
                )
                supersedes = previous_same or supersedes
                prior = sum(
                    json.loads(old["rule_json"])["schema_id"] == rule.schema_id
                    for old in prior_rows
                )
                version = "learned-" + hashlib.sha256(
                    _json([candidate_id, prior + 1, kind, asdict(rule), source_unit,
                           normalized_unit]).encode()
                ).hexdigest()[:24]
                db.execute(
                    "INSERT INTO learning_contracts VALUES (?,?,?,?,?,?,?,?,?)",
                    (version, candidate_id, _json(asdict(rule)), source_unit,
                     normalized_unit, supersedes, "ACTIVE", actor, now),
                )
                if supersedes:
                    db.execute(
                        "UPDATE learning_contracts SET status='INACTIVE' "
                        "WHERE learning_version=?", (supersedes,),
                    )
                    db.execute(
                        "UPDATE learning_candidates SET status='INACTIVE' "
                        "WHERE learning_version=?", (supersedes,),
                    )
            db.execute(
                "UPDATE learning_candidates SET status=?,confirmed_kind=?,learning_version=? "
                "WHERE candidate_id=?",
                (target, kind, version, candidate_id),
            )
            db.execute(
                "INSERT INTO learning_events VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, candidate_id, action, actor, row["status"], target, now),
            )
        return self.get_candidate(candidate_id) or {}

    def active_rules(self) -> tuple[SchemaRule, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT rule_json FROM learning_contracts WHERE status='ACTIVE' "
                "ORDER BY approved_at,learning_version"
            ).fetchall()
        return tuple(
            SchemaRule(**{**(data := json.loads(row[0])),
                          "required_columns": tuple(data["required_columns"])})
            for row in rows
        )

    def list_contracts(self) -> list[dict]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT learning_version,candidate_id,source_unit,normalized_unit,"
                "supersedes_version,status,approved_by,approved_at FROM learning_contracts "
                "ORDER BY approved_at DESC,learning_version DESC LIMIT 100"
            )]

    def list_events(self) -> list[dict]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT candidate_id,action,actor,before_status,after_status,recorded_at "
                "FROM learning_events ORDER BY recorded_at DESC,event_id DESC LIMIT 100"
            )]

    def validation_failed(self, candidate_id: str, actor: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status FROM learning_candidates WHERE candidate_id=?", (candidate_id,),
            ).fetchone()
            if row is None or row["status"] not in {"PENDING_OPERATOR", "PENDING_ADMIN"}:
                raise ValueError("LEARNING_CANDIDATE_NOT_PENDING")
            db.execute(
                "UPDATE learning_candidates SET status='PENDING_ADMIN' WHERE candidate_id=?",
                (candidate_id,),
            )
            db.execute(
                "INSERT INTO learning_events VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, candidate_id, "VALIDATION_FAILED", actor,
                 row["status"], "PENDING_ADMIN", now),
            )

    def deactivate(self, learning_version: str, actor: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT candidate_id,status FROM learning_contracts WHERE learning_version=?",
                (learning_version,),
            ).fetchone()
            if row is None:
                raise ValueError("LEARNING_CONTRACT_NOT_FOUND")
            if row["status"] == "INACTIVE":
                return
            db.execute(
                "UPDATE learning_contracts SET status='INACTIVE' WHERE learning_version=?",
                (learning_version,),
            )
            db.execute(
                "UPDATE learning_candidates SET status='INACTIVE' "
                "WHERE candidate_id=? AND learning_version=?",
                (row["candidate_id"], learning_version),
            )
            db.execute(
                "INSERT INTO learning_events VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, row["candidate_id"], "ADMIN_DEACTIVATE", actor,
                 "ACTIVE", "INACTIVE", now),
            )
