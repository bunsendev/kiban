"""Consent-bound encrypted Portable feedback outbox. No raw files or raw logs."""

import hashlib
import json
import os
import re
import sqlite3
import threading
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from forecast_provider.feedback_sync.client import connection_test
from forecast_provider.feedback_sync.crypto import encrypt_package
from forecast_provider.feedback_sync.policy import FeedbackStore
from forecast_provider.feedback_sync.transport import SharedServerTransport, _endpoint, send_pending
from portable import APP_VERSION
from portable.api.business_archive import atomic_json
from portable.runtime.api_credentials import ApiCredentials

DEFAULT_ENDPOINT = "https://bun.stock-tools.tech/upload.php"


class FeedbackDelivery:
    def __init__(self, paths):
        self.paths = paths
        self.config_path = paths.state / "delivery-config.json"
        self.store = FeedbackStore(paths.state / "delivery-outbox.sqlite3")
        identity = hashlib.sha256(str(paths.root).encode()).hexdigest()[:24]
        base = Path(os.environ.get("LOCALAPPDATA", str(paths.state)))
        self.token = ApiCredentials(
            base / "Bunsen/Portable/Credentials" / f"feedback-{identity}.dpapi"
        )
        self.lock = threading.RLock()
        with self.store._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS cursors(name TEXT PRIMARY KEY, value INTEGER)")

    def config(self):
        if self.config_path.exists():
            return json.loads(self.config_path.read_text("utf-8"))
        return {
            "enabled": False,
            "include_comments": False,
            "endpoint": DEFAULT_ENDPOINT,
            "client_id": "",
            "public_key": "",
            "revision": "unconfigured",
        }

    def configure(self, value):
        with self.lock:
            old = self.config()
            if value.get("enabled") is False:
                atomic_json(self.config_path, {**old, "enabled": False})
                return self.status()
            if value.get("consent") is not True:
                raise ValueError("送信内容と送信先への同意を確認してください")
            client_id = value.get("client_id", "")
            if not isinstance(client_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,80}", client_id
            ):
                raise ValueError("登録済み端末IDを英数字で入力してください")
            endpoint = value.get("endpoint", "")
            token = value.get("token") or self.token.load()
            _endpoint(endpoint, token)
            pem = value.get("public_key", "")
            if not isinstance(pem, str) or len(pem) > 8192:
                raise ValueError("受信サーバーの公開鍵を確認してください")
            key = serialization.load_pem_public_key(pem.encode())
            if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
                raise ValueError("受信サーバーのRSA公開鍵（3072bit以上）が必要です")
            config = {
                "enabled": True,
                "endpoint": endpoint,
                "client_id": client_id,
                "public_key": pem,
                "include_comments": value.get("include_comments") is True,
            }
            revision = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:32]
            config["revision"] = revision
            self.token.save(token)
            # Old consent/destination contents must never escape under new settings.
            with self.store._db() as db:
                db.execute(
                    "UPDATE outbox SET state='REJECTED',last_error='CONSENT_CHANGED' "
                    "WHERE state!='SENT' AND policy_version!=?",
                    (revision,),
                )
            atomic_json(self.config_path, config)
            return self.status()

    def status(self):
        config = self.config()
        with self.store._db() as db:
            last = db.execute(
                "SELECT state,last_error,created_at,sent_at FROM outbox "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return {
            "config": config,
            "token_saved": self.token.status()["available"],
            **self.store.status(),
            "last": dict(last) if last else None,
        }

    def collect(self):
        """Create one bounded incremental package, advance cursors atomically with queue."""
        config = self.config()
        with self.store._db() as db:
            cursors = dict(db.execute("SELECT name,value FROM cursors").fetchall())
        updated = dict(cursors)
        counts = Counter()
        comments = []
        jobs_path = self.paths.state / "field-ui.sqlite3"
        if jobs_path.exists():
            with sqlite3.connect(jobs_path, timeout=10) as source:
                source.execute("PRAGMA query_only=ON")
                for identifier, raw in source.execute("SELECT id,payload FROM jobs"):
                    cursor = "job:" + identifier
                    job = json.loads(raw)
                    state = job.get("status")
                    if cursor not in updated and state in {"SUCCEEDED", "FAILED", "INTERRUPTED"}:
                        updated[cursor] = 1
                        counts["job_" + state] += 1
        specs = [
            ("field-ui.sqlite3", "help_feedback", "id"),
            ("field-ui.sqlite3", "observations", "id"),
            ("field-operation-events.sqlite3", "operation_events", "rowid"),
        ]
        for filename, table, key in specs:
            path = self.paths.state / filename
            if not path.exists():
                continue
            with sqlite3.connect(path, timeout=10) as source:
                source.execute("PRAGMA query_only=ON")
                source.row_factory = sqlite3.Row
                records = source.execute(
                    f"SELECT {key} AS cursor_id,* FROM {table} "
                    f"WHERE {key}>? ORDER BY {key} LIMIT 50",
                    (cursors.get(table, 0),),
                ).fetchall()
            for record in records:
                updated[table] = record["cursor_id"]
                if table == "operation_events":
                    event = record["event_name"]
                    if event in {
                        "STEP_VIEWED",
                        "SOURCE_SELECTED",
                        "ANALYSIS_REQUESTED",
                        "ANALYSIS_ACCEPTED",
                        "ANALYSIS_FAILED",
                        "ANALYSIS_RESULT_FAILED",
                    }:
                        counts[event] += 1
                else:
                    counts[table] += 1
                    if table == "observations":
                        choice = json.loads(record["payload"]).get("choice")
                        if choice in {"ACCEPT", "CHANGE", "HOLD"}:
                            counts["judgment_" + choice] += 1
                    if table == "help_feedback" and config["include_comments"]:
                        item = json.loads(record["payload"])
                        comments.append(
                            {"step": item.get("step"), "comment": item["comment"][:2000]}
                        )
        if updated == cursors:
            return
        payload = {
            "format": "bunsen-portable-feedback-v1",
            "application_version": APP_VERSION,
            "counts": dict(counts),
            "comments": comments,
            "contains_raw_files": False,
            "contains_raw_logs": False,
        }
        identifier = hashlib.sha256(
            json.dumps([config["client_id"], config["revision"], updated], sort_keys=True).encode()
        ).hexdigest()[:32]
        envelope = encrypt_package(
            {"category": "PORTABLE_FEEDBACK", "payload": payload},
            config["public_key"].encode(),
            package_id=identifier,
            client_id=config["client_id"],
        )
        with self.store._db() as db:
            db.execute(
                "INSERT OR IGNORE INTO outbox VALUES(?,?,?,?,?,'PENDING',0,NULL,NULL,NULL,?,?)",
                (
                    identifier,
                    datetime.now(UTC).isoformat(),
                    config["revision"],
                    envelope,
                    hashlib.sha256(envelope).hexdigest(),
                    config["endpoint"],
                    "shared_php",
                ),
            )
            db.executemany("INSERT OR REPLACE INTO cursors VALUES(?,?)", updated.items())
        return True

    def send(self, *, manual=False):
        with self.lock:
            config = self.config()
            if not config["enabled"]:
                return self.status()
            # Bounded batches; queue before network work, retain remaining source records.
            for _ in range(20):
                if not self.collect():
                    break
            token = self.token.load()
            if manual:
                with self.store._db() as db:
                    db.execute(
                        "UPDATE outbox SET state='PENDING' WHERE state='REJECTED' "
                        "AND last_error='HTTP_401' AND policy_version=?",
                        (config["revision"],),
                    )
            send_pending(
                self.store,
                url=config["endpoint"],
                token=token,
                force=manual,
                transport=SharedServerTransport(config["endpoint"], config["client_id"]),
            )
            return self.status()

    def connection_test(self):
        with self.lock:
            config = self.config()
            if not config["enabled"]:
                raise ValueError("先に送信設定を確認してください")
            return connection_test(
                {**config, "transport": "shared_php"},
                self.token.load(), config["public_key"].encode(),
            )
