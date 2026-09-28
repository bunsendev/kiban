"""現場設定を版ごとに追記し、変更履歴を削除せず保持する。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TYPES = {"JAN_MAPPING", "INVENTORY_TIME_POLICY"}


class LocalSettingStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS setting_changes (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    change_id TEXT NOT NULL UNIQUE,
                    version TEXT NOT NULL UNIQUE,
                    change_type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    effective_from TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    old_version TEXT,
                    reason_code TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    application_version TEXT NOT NULL,
                    rollback_of TEXT
                );
                CREATE INDEX IF NOT EXISTS setting_changes_target_idx
                  ON setting_changes(change_type,target,effective_from,sequence);
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _public(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["value"] = json.loads(result.pop("value_json"))
        return result

    def current(self, change_type: str, target: str, *, business_date: date | None = None,
                known_at: datetime | None = None) -> dict | None:
        if change_type not in TYPES or not target:
            raise ValueError("LOCAL_SETTING_KEY_INVALID")
        day = business_date or datetime.now(ZoneInfo("Asia/Tokyo")).date()
        observed = known_at or datetime.now(UTC)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("LOCAL_SETTING_TIME_INVALID")
        observed = observed.astimezone(UTC)
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM setting_changes WHERE change_type=? AND target=? "
                "AND effective_from<=? AND changed_at<=? "
                "ORDER BY sequence DESC LIMIT 1",
                (change_type, target, day.isoformat(), observed.isoformat()),
            ).fetchone()
        return None if row is None else self._public(row)

    def history(self, change_type: str, target: str) -> list[dict]:
        if change_type not in TYPES or not target:
            raise ValueError("LOCAL_SETTING_KEY_INVALID")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM setting_changes WHERE change_type=? AND target=? "
                "ORDER BY sequence DESC", (change_type, target),
            ).fetchall()
        return [self._public(row) for row in rows]

    def targets(self, change_type: str) -> list[str]:
        if change_type not in TYPES:
            raise ValueError("LOCAL_SETTING_TYPE_INVALID")
        with self._connect() as db:
            rows = db.execute(
                "SELECT DISTINCT target FROM setting_changes WHERE change_type=? ORDER BY target",
                (change_type,),
            ).fetchall()
        return [row["target"] for row in rows]

    def append(self, *, change_type: str, target: str, value: dict,
               effective_from: date, actor: str, reason_code: str,
               comment: str, application_version: str,
               expected_version: str | None, rollback_of: str | None = None,
               changed_at: datetime | None = None) -> dict:
        if change_type not in TYPES or not target:
            raise ValueError("LOCAL_SETTING_KEY_INVALID")
        now = changed_at or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("LOCAL_SETTING_TIME_INVALID")
        now = now.astimezone(UTC)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT version FROM setting_changes WHERE change_type=? AND target=? "
                "ORDER BY sequence DESC LIMIT 1", (change_type, target),
            ).fetchone()
            old_version = None if current is None else current["version"]
            if old_version != expected_version:
                raise ValueError("LOCAL_SETTING_VERSION_CONFLICT")
            version = "local-" + uuid.uuid4().hex
            change_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO setting_changes "
                "(change_id,version,change_type,target,value_json,effective_from,changed_at,"
                "actor,old_version,reason_code,comment,application_version,rollback_of) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (change_id, version, change_type, target,
                 json.dumps(value, ensure_ascii=False, sort_keys=True),
                 effective_from.isoformat(), now.isoformat(), actor, old_version,
                 reason_code, comment, application_version, rollback_of),
            )
            row = db.execute(
                "SELECT * FROM setting_changes WHERE change_id=?", (change_id,),
            ).fetchone()
        return self._public(row)

    def version(self, version: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM setting_changes WHERE version=?", (version,),
            ).fetchone()
        return None if row is None else self._public(row)
