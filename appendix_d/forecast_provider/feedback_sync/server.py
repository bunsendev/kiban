"""中央Feedback受信。復号後にもClient Policyと項目契約を検証する。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.exceptions import InvalidKey, InvalidTag
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .crypto import decrypt_package
from .policy import FLAGS, validate_policy
from .privacy import SAFE_METRICS, validate_package
from .support import validate_support

DEFAULT_RETENTION = {"DIAGNOSTIC": 30, "IMPROVEMENT": 90, "SUPPORT": 7}


class FeedbackServerStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS clients (
                    client_id TEXT PRIMARY KEY, token_sha256 TEXT NOT NULL,
                    policy_version TEXT NOT NULL, policy_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS received (
                    package_id TEXT PRIMARY KEY, client_id TEXT NOT NULL,
                    received_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                    policy_version TEXT NOT NULL, category TEXT NOT NULL,
                    envelope_sha256 TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS received_retention ON received(category,received_at);
                CREATE TABLE IF NOT EXISTS support_grants (
                    consent_id TEXT PRIMARY KEY, client_id TEXT NOT NULL,
                    file_sha256 TEXT NOT NULL, expires_at TEXT NOT NULL,
                    max_bytes INTEGER NOT NULL, used_package_id TEXT
                );
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enroll(self, client_id: str, token: str, policy_version: str, policy: dict) -> None:
        validated = validate_policy(policy)
        if (not client_id.isascii() or not client_id.replace("-", "").replace("_", "").isalnum()
                or not 1 <= len(client_id) <= 80 or len(token) < 32 or not policy_version):
            raise ValueError("FEEDBACK_ENROLLMENT_INVALID")
        with self._db() as db:
            db.execute("INSERT INTO clients VALUES (?,?,?,?,1) ON CONFLICT(client_id) DO UPDATE "
                       "SET token_sha256=excluded.token_sha256,"
                       "policy_version=excluded.policy_version,policy_json=excluded.policy_json,"
                       "enabled=1", (
                           client_id, hashlib.sha256(token.encode()).hexdigest(), policy_version,
                           json.dumps(validated, sort_keys=True),
                       ))

    def client(self, client_id: str, token: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM clients WHERE client_id=? AND enabled=1",
                             (client_id,)).fetchone()
        if row is None or not hmac.compare_digest(
            row["token_sha256"], hashlib.sha256(token.encode()).hexdigest(),
        ):
            return None
        return {"policy_version": row["policy_version"],
                "policy": json.loads(row["policy_json"])}

    def grant_support(self, *, client_id: str, consent_id: str, file_sha256: str,
                      expires_at: datetime, max_bytes: int) -> None:
        if (len(consent_id) != 32 or len(file_sha256) != 64
                or any(c not in "0123456789abcdef" for c in consent_id + file_sha256)
                or expires_at.tzinfo is None or expires_at <= datetime.now(UTC)
                or not 0 < max_bytes <= 5_000_000):
            raise ValueError("SUPPORT_GRANT_INVALID")
        with self._db() as db:
            enrolled = db.execute("SELECT 1 FROM clients WHERE client_id=?",
                                  (client_id,)).fetchone()
            if enrolled is None:
                raise ValueError("SUPPORT_CLIENT_UNKNOWN")
            db.execute("INSERT INTO support_grants VALUES (?,?,?,?,?,NULL)", (
                consent_id, client_id, file_sha256, expires_at.astimezone(UTC).isoformat(),
                max_bytes,
            ))

    def accept(self, client_id: str, package_id: str, package: dict,
               envelope_sha256: str) -> str:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT client_id,envelope_sha256 FROM received WHERE package_id=?",
                             (package_id,)).fetchone()
            if row is not None:
                if row["client_id"] != client_id or row["envelope_sha256"] != envelope_sha256:
                    raise ValueError("FEEDBACK_PACKAGE_ID_CONFLICT")
                return "DUPLICATE"
            db.execute("INSERT INTO received VALUES (?,?,?,?,?,?,?)", (
                package_id, client_id, datetime.now(UTC).isoformat(),
                json.dumps(package["payload"], sort_keys=True, separators=(",", ":")),
                package["manifest"]["policy_version"],
                "DIAGNOSTIC" if package["level"] == 1 else "IMPROVEMENT",
                envelope_sha256,
            ))
        return "ACCEPTED"

    def accept_support(self, client_id: str, package_id: str, consent_id: str,
                       file_sha256: str, file_size: int, envelope: bytes) -> str:
        digest = hashlib.sha256(envelope).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT client_id,envelope_sha256 FROM received "
                                  "WHERE package_id=?", (package_id,)).fetchone()
            if existing is not None:
                if existing["client_id"] != client_id or existing["envelope_sha256"] != digest:
                    raise ValueError("SUPPORT_PACKAGE_ID_CONFLICT")
                return "DUPLICATE"
            grant = db.execute("SELECT * FROM support_grants WHERE consent_id=?",
                               (consent_id,)).fetchone()
            if (grant is None or grant["client_id"] != client_id
                    or grant["file_sha256"] != file_sha256
                    or grant["expires_at"] <= datetime.now(UTC).isoformat()
                    or file_size > grant["max_bytes"] or grant["used_package_id"] is not None):
                raise ValueError("SUPPORT_GRANT_REJECTED")
            db.execute("UPDATE support_grants SET used_package_id=? WHERE consent_id=?",
                       (package_id, consent_id))
            db.execute("INSERT INTO received VALUES (?,?,?,?,?,?,?)", (
                package_id, client_id, datetime.now(UTC).isoformat(),
                base64.b64encode(envelope).decode(), consent_id, "SUPPORT", digest,
            ))
        return "ACCEPTED"

    def prune(self, retention: dict[str, int] | None = None) -> int:
        retention = retention or DEFAULT_RETENTION
        if (set(retention) != set(DEFAULT_RETENTION)
                or any(type(days) is not int or not 1 <= days <= 3650
                       for days in retention.values())):
            raise ValueError("FEEDBACK_RETENTION_INVALID")
        deleted = 0
        with self._db() as db:
            for category, days in retention.items():
                cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
                result = db.execute("DELETE FROM received WHERE category=? AND received_at<?",
                                    (category, cutoff))
                deleted += result.rowcount
        return deleted


def create_server(store: FeedbackServerStore, private_pem: bytes, *,
                  require_tls: bool = True,
                  retention: dict[str, int] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        async def cleanup():
            while True:
                store.prune(retention)
                await asyncio.sleep(86_400)

        task = asyncio.create_task(cleanup())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.post("/v1/feedback")
    async def receive(request: Request):
        if require_tls and request.url.scheme != "https":
            return JSONResponse({"error": "TLS_REQUIRED"}, status_code=403)
        body = await request.body()
        if len(body) > 10_000_000:
            return JSONResponse({"error": "PACKAGE_TOO_LARGE"}, status_code=413)
        try:
            outer = json.loads(body)
            client_id = outer["client_id"]
            package_id = outer["package_id"]
            if (not isinstance(client_id, str) or not 1 <= len(client_id) <= 80
                    or not client_id.isascii() or not isinstance(package_id, str)
                    or len(package_id) != 32
                    or any(c not in "0123456789abcdef" for c in package_id)):
                raise ValueError("INVALID_ID")
            authorization = request.headers.get("authorization", "")
            if not authorization.startswith("Bearer "):
                return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
            registered = store.client(client_id, authorization[7:])
            if registered is None:
                return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
            envelope, package = decrypt_package(body, private_pem)
            if envelope["client_id"] != client_id or envelope["package_id"] != package_id:
                raise ValueError("ENVELOPE_ID_MISMATCH")
            if package.get("category") == "SUPPORT":
                consent_id, file_sha256, content = validate_support(package)
                status = store.accept_support(client_id, package_id, consent_id,
                                              file_sha256, len(content), body)
                return {"status": status, "package_id": package_id}
            approved = registered["policy"]
            validate_package(package, max_level=approved["level"])
            if package["manifest"]["policy_version"] != registered["policy_version"]:
                raise ValueError("POLICY_VERSION_UNAPPROVED")
            flags = approved["flags"]
            if ((package["payload"]["event_counts"] and not flags["diagnostics"])
                    or (package["payload"]["details"] and not flags["diagnostics"])
                    or (package["payload"]["metric_summary"] and not flags["forecast_metrics"])
                    or (any(set(item["metrics"]) & SAFE_METRICS
                            for item in package["payload"]["details"])
                        and not flags["forecast_metrics"])
                    or (any("product_id" in item for item in package["payload"]["details"])
                    and not flags["pseudonymous_products"])
                    or (any("warehouse_id" in item for item in package["payload"]["details"])
                    and not flags["pseudonymous_warehouses"])
                    or (package["manifest"]["contains_absolute_inventory"]
                    and not flags["absolute_quantities"])):
                raise ValueError("POLICY_FIELDS_UNAPPROVED")
            if set(flags) != FLAGS:
                raise ValueError("POLICY_FLAGS_INVALID")
            status = store.accept(client_id, package_id, package,
                                  hashlib.sha256(body).hexdigest())
            return {"status": status, "package_id": package_id}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, IndexError,
                binascii.Error, UnicodeDecodeError, InvalidKey, InvalidTag):
            return JSONResponse({"error": "PACKAGE_REJECTED"}, status_code=422)

    return app


def from_environment() -> FastAPI:
    db_path, key_path = os.environ.get("KIBAN_FEEDBACK_DB"), os.environ.get(
        "KIBAN_FEEDBACK_PRIVATE_KEY_FILE",
    )
    if not db_path or not key_path:
        raise RuntimeError("Feedback server store/key is required")
    return create_server(FeedbackServerStore(Path(db_path)), Path(key_path).read_bytes())
