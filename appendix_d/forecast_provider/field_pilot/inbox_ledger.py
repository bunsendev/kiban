"""投入履歴と採用状態を追記し、必要ファイルを日別に照合する。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .inbox_classifier import Classification
from .inbox_policy import InboxPolicy

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox_files (
    stage_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    source_name_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    kind TEXT,
    location_id TEXT,
    target_date TEXT,
    schema_id TEXT,
    mapping_version TEXT,
    policy_version TEXT NOT NULL,
    archive_reference TEXT NOT NULL,
    received_at TEXT NOT NULL,
    processed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_inbox_hash ON inbox_files(sha256);
CREATE INDEX IF NOT EXISTS ix_inbox_required
    ON inbox_files(kind, location_id, target_date, processed_at);
"""


class InboxLedger:
    def __init__(self, path: Path):
        self.path = path
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("INBOX_LEDGER_PATH_INVALID")
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def has_stage(self, stage_id: str) -> bool:
        with self._connect() as db:
            return db.execute(
                "SELECT 1 FROM inbox_files WHERE stage_id=?", (stage_id,)
            ).fetchone() is not None

    def has_hash(self, sha256: str, policy_version: str) -> bool:
        with self._connect() as db:
            return db.execute(
                "SELECT 1 FROM inbox_files WHERE sha256=? AND policy_version=? "
                "AND status IN ('PROCESSED','RECEIVED','REVISION_CANDIDATE','DUPLICATE') "
                "LIMIT 1",
                (sha256, policy_version),
            ).fetchone() is not None

    def has_previous(self, classification: Classification, sha256: str) -> bool:
        if classification.key is None:
            return False
        with self._connect() as db:
            return db.execute(
                "SELECT 1 FROM inbox_files WHERE kind=? AND location_id=? "
                "AND target_date=? AND sha256!=? AND status='PROCESSED' LIMIT 1",
                (*classification.key, sha256),
            ).fetchone() is not None

    def record(
        self, *, stage_id: str, sha256: str, source_name_sha256: str,
        size_bytes: int, status: str, reason: str, classification: Classification,
        policy_version: str, archive_reference: str, received_at: str,
    ) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO inbox_files(stage_id,sha256,source_name_sha256,size_bytes,"
                "status,reason,kind,location_id,target_date,schema_id,mapping_version,"
                "policy_version,archive_reference,received_at,processed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    stage_id, sha256, source_name_sha256, size_bytes, status, reason,
                    classification.kind, classification.location_id,
                    classification.target_date, classification.schema_id,
                    classification.mapping_version, policy_version, archive_reference,
                    received_at, datetime.now(UTC).isoformat(),
                ),
            )

    def summary(self, policy: InboxPolicy, target_date: str) -> dict:
        day_start = datetime.fromisoformat(target_date).replace(
            tzinfo=ZoneInfo("Asia/Tokyo")
        ).astimezone(UTC)
        day_end = day_start + timedelta(days=1)
        latest = (
            "WITH ranked AS (SELECT *,ROW_NUMBER() OVER ("
            "PARTITION BY sha256 ORDER BY processed_at DESC,stage_id DESC) AS rn "
            "FROM inbox_files WHERE policy_version=? AND status!='DUPLICATE') "
        )
        with self._connect() as db:
            rows = db.execute(
                latest + "SELECT kind,location_id,status,processed_at FROM ranked "
                "WHERE rn=1 AND target_date=? ORDER BY processed_at",
                (policy.version, target_date),
            ).fetchall()
            counts = db.execute(
                latest + "SELECT status,count(*) FROM ranked WHERE rn=1 "
                "AND processed_at>=? AND processed_at<? GROUP BY status",
                (policy.version, day_start.isoformat(), day_end.isoformat()),
            ).fetchall()
            duplicates = db.execute(
                "SELECT count(*) FROM inbox_files WHERE policy_version=? "
                "AND status='DUPLICATE' AND processed_at>=? AND processed_at<?",
                (policy.version, day_start.isoformat(), day_end.isoformat()),
            ).fetchone()[0]
            updated = db.execute(
                "SELECT max(processed_at) FROM inbox_files WHERE policy_version=?",
                (policy.version,),
            ).fetchone()[0]
        by_key: dict[tuple[str, str], set[str]] = {}
        for row in rows:
            by_key.setdefault((row["kind"], row["location_id"]), set()).add(row["status"])
        required = []
        for item in policy.required:
            found = by_key.get(item.key, set())
            state = (
                "REVIEW_REQUIRED" if "REVISION_CANDIDATE" in found
                else "VALID" if "PROCESSED" in found
                else "REVIEW_REQUIRED" if "REVIEW_REQUIRED" in found
                else "INVALID" if "REJECTED" in found
                else "RECEIVED" if "RECEIVED" in found
                else "MISSING"
            )
            required.append({
                "kind": item.kind, "location_id": item.location_id,
                "display_name": item.display_name, "status": state,
            })
        total = dict(counts)
        review_count = sum(total.get(key, 0) for key in (
            "REVIEW_REQUIRED", "REVISION_CANDIDATE", "UNKNOWN", "REJECTED"
        ))
        return {
            "status": "READY" if required and all(
                item["status"] == "VALID" for item in required
            ) and review_count == 0 else "MISSING_OR_REVIEW",
            "policy_version": policy.version,
            "target_date": target_date,
            "required": required,
            "checked_count": sum(total.values()) + duplicates,
            "processed_count": total.get("PROCESSED", 0),
            "received_count": total.get("RECEIVED", 0),
            "review_count": review_count,
            "duplicate_count": duplicates,
            "last_updated_at": updated,
        }
