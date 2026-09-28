"""版付き共有Policyと監査台帳。未設定時は送信しない。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

FLAGS = frozenset({
    "diagnostics", "forecast_metrics", "operator_corrections", "business_kpis",
    "pseudonymous_products", "pseudonymous_warehouses", "absolute_quantities",
    "expiry_dates",
    "learning_summary", "change_summary", "data_freshness",
})
DEFAULT_FLAGS = dict.fromkeys(FLAGS, False)
MAX_LEVEL = 3


def validate_policy(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"level", "flags"}:
        raise ValueError("FEEDBACK_POLICY_INVALID")
    level, flags = value["level"], value["flags"]
    if (type(level) is not int or not 0 <= level <= MAX_LEVEL
            or not isinstance(flags, dict) or set(flags) != FLAGS
            or any(type(item) is not bool for item in flags.values())):
        raise ValueError("FEEDBACK_POLICY_INVALID")
    if level == 0 and any(flags.values()):
        raise ValueError("FEEDBACK_POLICY_OFF_CONFLICT")
    if level < 2 and any(flags[name] for name in (
        "learning_summary", "change_summary", "data_freshness",
    )):
        raise ValueError("FEEDBACK_POLICY_LEVEL_CONFLICT")
    if level < 3 and any(flags[name] for name in (
        "pseudonymous_products", "pseudonymous_warehouses", "absolute_quantities",
        "expiry_dates",
    )):
        raise ValueError("FEEDBACK_POLICY_LEVEL_CONFLICT")
    return {"level": level, "flags": {name: flags[name] for name in sorted(FLAGS)}}


class FeedbackStore:
    def __init__(self, path: Path):
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("FEEDBACK_STORE_PATH_INVALID")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS policies (
                    version TEXT PRIMARY KEY, previous_version TEXT, changed_at TEXT NOT NULL,
                    changed_by TEXT NOT NULL, reason TEXT NOT NULL, policy_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
                    action TEXT NOT NULL, reference TEXT, detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    package_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    policy_version TEXT NOT NULL, envelope BLOB NOT NULL,
                    sha256 TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT, sent_at TEXT, next_attempt_at TEXT,
                    destination_url TEXT, transport_kind TEXT
                );
                CREATE TABLE IF NOT EXISTS consents (
                    consent_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL, target TEXT NOT NULL, purpose TEXT NOT NULL,
                    destination TEXT NOT NULL, actor TEXT NOT NULL, used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS update_checks (
                    checked_at TEXT NOT NULL, status TEXT NOT NULL, available_version TEXT
                );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(outbox)")}
            if "next_attempt_at" not in columns:
                db.execute("ALTER TABLE outbox ADD COLUMN next_attempt_at TEXT")
            if "destination_url" not in columns:
                db.execute("ALTER TABLE outbox ADD COLUMN destination_url TEXT")
            if "transport_kind" not in columns:
                db.execute("ALTER TABLE outbox ADD COLUMN transport_kind TEXT")

    @contextmanager
    def _db(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def current(self) -> dict:
        with self._db() as db:
            row = db.execute("SELECT * FROM policies ORDER BY rowid DESC LIMIT 1").fetchone()
        if row is None:
            return {"version": None, "previous_version": None,
                    "policy": {"level": 0, "flags": DEFAULT_FLAGS.copy()}}
        return {"version": row["version"], "previous_version": row["previous_version"],
                "policy": json.loads(row["policy_json"]), "changed_at": row["changed_at"],
                "changed_by": row["changed_by"]}

    def change(self, value: dict, *, expected_version: str | None,
               actor: str, reason: str) -> dict:
        policy = validate_policy(value)
        if not actor.strip() or not reason.strip() or len(actor) > 120 or len(reason) > 500:
            raise ValueError("FEEDBACK_POLICY_AUDIT_INVALID")
        now = datetime.now(UTC).isoformat()
        version = "feedback-" + uuid.uuid4().hex
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT version FROM policies ORDER BY rowid DESC LIMIT 1",
            ).fetchone()
            previous = None if current is None else current["version"]
            if previous != expected_version:
                raise ValueError("FEEDBACK_POLICY_VERSION_CONFLICT")
            db.execute("INSERT INTO policies VALUES (?,?,?,?,?,?)", (
                version, previous, now, actor.strip(), reason.strip(),
                json.dumps(policy, sort_keys=True, separators=(",", ":")),
            ))
            db.execute("INSERT INTO audit(occurred_at,action,reference,detail) VALUES (?,?,?,?)",
                       (now, "POLICY_CHANGED", version, reason.strip()))
        return self.current()

    def audit(self, action: str, reference: str | None = None, detail: str = "") -> None:
        if action not in {"PACKAGE_CREATED", "SENT", "FAILED_RETRYABLE", "REJECTED",
                          "SUPPORT_CONSENT", "SUPPORT_USED", "POLICY_REJECTED"}:
            raise ValueError("FEEDBACK_AUDIT_ACTION_INVALID")
        with self._db() as db:
            db.execute("INSERT INTO audit(occurred_at,action,reference,detail) VALUES (?,?,?,?)",
                       (datetime.now(UTC).isoformat(), action, reference, detail[:500]))

    def queue(self, package_id: str, policy_version: str, envelope: bytes, *,
              destination_url: str | None = None, transport_kind: str = "api") -> None:
        if len(envelope) > 10_000_000:
            raise ValueError("FEEDBACK_ENVELOPE_TOO_LARGE")
        if transport_kind not in {"api", "shared_php"}:
            raise ValueError("FEEDBACK_TRANSPORT_INVALID")
        with self._db() as db:
            db.execute("INSERT INTO outbox VALUES "
                       "(?,?,?,?,?,'PENDING',0,NULL,NULL,NULL,?,?)", (
                package_id, datetime.now(UTC).isoformat(), policy_version, envelope,
                hashlib.sha256(envelope).hexdigest(), destination_url, transport_kind,
            ))
            db.execute("INSERT INTO audit(occurred_at,action,reference,detail) VALUES (?,?,?,?)",
                       (datetime.now(UTC).isoformat(), "PACKAGE_CREATED", package_id, ""))

    def pending(self, *, force: bool = True) -> list[dict]:
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM outbox WHERE state IN ('PENDING','FAILED_RETRYABLE') "
                "AND (? OR next_attempt_at IS NULL OR next_attempt_at<=?) "
                "ORDER BY created_at,package_id LIMIT 100",
                (int(force), datetime.now(UTC).isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]

    def unsent_count(self) -> int:
        with self._db() as db:
            return db.execute("SELECT COUNT(*) FROM outbox WHERE state IN "
                              "('PENDING','FAILED_RETRYABLE','UPLOADING')").fetchone()[0]

    def mark(self, package_id: str, state: str, error_code: str | None = None) -> None:
        if state not in {"UPLOADING", "SENT", "FAILED_RETRYABLE", "REJECTED"}:
            raise ValueError("FEEDBACK_OUTBOX_STATE_INVALID")
        with self._db() as db:
            next_attempt = None
            if state == "FAILED_RETRYABLE":
                attempts = db.execute("SELECT attempts FROM outbox WHERE package_id=?",
                                      (package_id,)).fetchone()
                minutes = min(1440, 5 * 2 ** min(8, max(0, attempts[0] - 1)))
                next_attempt = (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()
            db.execute("UPDATE outbox SET state=?,attempts=attempts+?,last_error=?,sent_at=?,"
                       "next_attempt_at=? "
                       "WHERE package_id=?", (
                           state, int(state == "UPLOADING"), error_code,
                           datetime.now(UTC).isoformat() if state == "SENT" else None,
                           next_attempt, package_id,
                       ))
        if state != "UPLOADING":
            self.audit(state, package_id, error_code or "")

    def recover_uploading(self) -> None:
        with self._db() as db:
            db.execute("UPDATE outbox SET state='FAILED_RETRYABLE',next_attempt_at=NULL "
                       "WHERE state='UPLOADING'")

    def record_update_check(self, status: str, available_version: str | None = None) -> None:
        if status not in {"AVAILABLE", "CURRENT", "UNAVAILABLE"}:
            raise ValueError("UPDATE_STATUS_INVALID")
        with self._db() as db:
            db.execute("INSERT INTO update_checks VALUES (?,?,?)", (
                datetime.now(UTC).isoformat(), status, available_version,
            ))

    def status(self) -> dict:
        with self._db() as db:
            rows = db.execute(
                "SELECT state,COUNT(*) AS count FROM outbox GROUP BY state",
            ).fetchall()
            last_sync = db.execute(
                "SELECT MAX(sent_at) FROM outbox WHERE state='SENT'",
            ).fetchone()[0]
            last_update = db.execute("SELECT checked_at,status,available_version "
                                     "FROM update_checks ORDER BY rowid DESC LIMIT 1").fetchone()
        counts = {row["state"]: row["count"] for row in rows}
        return {"last_sync": last_sync,
                "pending_outbox": sum(counts.get(state, 0) for state in (
                    "PENDING", "FAILED_RETRYABLE", "UPLOADING",
                )), "rejected_package": counts.get("REJECTED", 0),
                "last_update_check": dict(last_update) if last_update else None}

    def prune_outbox(self, *, sent_days: int = 30, rejected_days: int = 90) -> int:
        if not 1 <= sent_days <= 3650 or not 1 <= rejected_days <= 3650:
            raise ValueError("FEEDBACK_OUTBOX_RETENTION_INVALID")
        deleted = 0
        with self._db() as db:
            for state, days in (("SENT", sent_days), ("REJECTED", rejected_days)):
                cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
                result = db.execute("DELETE FROM outbox WHERE state=? AND created_at<?",
                                    (state, cutoff))
                deleted += result.rowcount
        return deleted

    def consent(self, *, target: str, purpose: str, destination: str,
                actor: str, expires_at: datetime) -> str:
        now = datetime.now(UTC)
        if (expires_at.tzinfo is None or not now < expires_at <= now + timedelta(days=30)
                or not target or not purpose or not destination or not actor
                or max(map(len, (target, purpose, destination, actor))) > 300):
            raise ValueError("FEEDBACK_CONSENT_INVALID")
        consent_id = uuid.uuid4().hex
        with self._db() as db:
            db.execute("INSERT INTO consents VALUES (?,?,?,?,?,?,?,NULL)", (
                consent_id, now.isoformat(), expires_at.astimezone(UTC).isoformat(),
                target, purpose, destination, actor,
            ))
        self.audit("SUPPORT_CONSENT", consent_id)
        return consent_id

    def use_consent(self, consent_id: str, *, target: str, destination: str) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._db() as db:
            result = db.execute("UPDATE consents SET used_at=? WHERE consent_id=? AND "
                                "target=? AND destination=? AND used_at IS NULL AND expires_at>?",
                                (now, consent_id, target, destination, now))
        if result.rowcount:
            self.audit("SUPPORT_USED", consent_id)
        return result.rowcount == 1
