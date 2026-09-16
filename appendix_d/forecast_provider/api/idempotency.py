"""作成APIを再送しても同じ結果へ収束させる共通HTTP境界。"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute

MAX_RESPONSE_BYTES = 1024 * 1024
PENDING_LEASE = timedelta(minutes=15)
KEY_PATTERN = re.compile(r"^[\x21-\x7e]{1,200}$")


@dataclass(frozen=True)
class IdempotencyRecord:
    request_hash: str
    state: str
    pending_until: str
    status_code: int | None = None
    media_type: str | None = None
    response_body: bytes | None = None


class IdempotencyStore(Protocol):
    def claim(
        self, scope_hash: str, request_hash: str, now: datetime
    ) -> tuple[str, IdempotencyRecord]: ...

    def complete(
        self,
        scope_hash: str,
        request_hash: str,
        status_code: int,
        media_type: str,
        response_body: bytes,
        now: datetime,
    ) -> None: ...

    def release(self, scope_hash: str, request_hash: str) -> None: ...


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def claim(self, scope_hash: str, request_hash: str, now: datetime):
        pending_until = (now + PENDING_LEASE).isoformat()
        with self._lock:
            current = self._records.get(scope_hash)
            if current is None or (
                current.state == "PENDING" and current.pending_until <= now.isoformat()
            ):
                current = IdempotencyRecord(request_hash, "PENDING", pending_until)
                self._records[scope_hash] = current
                return "CLAIMED", current
            if current.request_hash != request_hash:
                return "MISMATCH", current
            return ("REPLAY" if current.state == "COMPLETED" else "IN_PROGRESS"), current

    def complete(self, scope_hash, request_hash, status_code, media_type, response_body, now):
        with self._lock:
            current = self._records.get(scope_hash)
            if current is None or current.request_hash != request_hash:
                raise RuntimeError("冪等性記録の所有権が失われました")
            self._records[scope_hash] = IdempotencyRecord(
                request_hash,
                "COMPLETED",
                current.pending_until,
                status_code,
                media_type,
                response_body,
            )

    def release(self, scope_hash: str, request_hash: str) -> None:
        with self._lock:
            current = self._records.get(scope_hash)
            if current is not None and current.request_hash == request_hash:
                self._records.pop(scope_hash)


class SqliteIdempotencyStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("idempotency_schema.sql").read_text("utf-8"))

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def claim(self, scope_hash: str, request_hash: str, now: datetime):
        pending_until = (now + PENDING_LEASE).isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM api_idempotency_records WHERE scope_hash=?", (scope_hash,)
            ).fetchone()
            if row is None or (
                row["state"] == "PENDING" and row["pending_until"] <= now.isoformat()
            ):
                db.execute(
                    "INSERT OR REPLACE INTO api_idempotency_records "
                    "VALUES (?,?, 'PENDING', ?,NULL,NULL,NULL,?,NULL)",
                    (scope_hash, request_hash, pending_until, now.isoformat()),
                )
                return "CLAIMED", IdempotencyRecord(request_hash, "PENDING", pending_until)
            record = _record(row)
            if record.request_hash != request_hash:
                return "MISMATCH", record
            return ("REPLAY" if record.state == "COMPLETED" else "IN_PROGRESS"), record

    def complete(self, scope_hash, request_hash, status_code, media_type, response_body, now):
        with self._connect() as db:
            changed = db.execute(
                "UPDATE api_idempotency_records SET state='COMPLETED',status_code=?,media_type=?,"
                "response_body=?,completed_at=? WHERE scope_hash=? AND request_hash=? "
                "AND state='PENDING'",
                (status_code, media_type, response_body, now.isoformat(), scope_hash, request_hash),
            ).rowcount
            if changed != 1:
                raise RuntimeError("冪等性記録の所有権が失われました")

    def release(self, scope_hash: str, request_hash: str) -> None:
        with self._connect() as db:
            db.execute(
                "DELETE FROM api_idempotency_records WHERE scope_hash=? AND request_hash=? "
                "AND state='PENDING'",
                (scope_hash, request_hash),
            )


class PostgresIdempotencyStore(SqliteIdempotencyStore):
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.path = Path(".")
        with self._raw_connect() as db:
            schema = Path(__file__).with_name("idempotency_schema.sql").read_text("utf-8")
            db.execute(schema.replace(" BLOB", " BYTEA"))

    def _raw_connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL利用にはpsycopgが必要です") from exc
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def claim(self, scope_hash: str, request_hash: str, now: datetime):
        pending_until = (now + PENDING_LEASE).isoformat()
        with self._raw_connect() as db:
            inserted = db.execute(
                "INSERT INTO api_idempotency_records "
                "VALUES (%s,%s,'PENDING',%s,NULL,NULL,NULL,%s,NULL) "
                "ON CONFLICT (scope_hash) DO NOTHING RETURNING scope_hash",
                (scope_hash, request_hash, pending_until, now.isoformat()),
            ).fetchone()
            if inserted is not None:
                return "CLAIMED", IdempotencyRecord(request_hash, "PENDING", pending_until)
            row = db.execute(
                "SELECT * FROM api_idempotency_records WHERE scope_hash=%s FOR UPDATE",
                (scope_hash,),
            ).fetchone()
            if row is None:
                raise RuntimeError("冪等性記録を取得できません")
            if row["state"] == "PENDING" and row["pending_until"] <= now.isoformat():
                db.execute(
                    "UPDATE api_idempotency_records SET request_hash=%s,pending_until=%s,"
                    "created_at=%s WHERE scope_hash=%s",
                    (request_hash, pending_until, now.isoformat(), scope_hash),
                )
                return "CLAIMED", IdempotencyRecord(request_hash, "PENDING", pending_until)
            record = _record(row)
            if record.request_hash != request_hash:
                return "MISMATCH", record
            return ("REPLAY" if record.state == "COMPLETED" else "IN_PROGRESS"), record

    def complete(self, scope_hash, request_hash, status_code, media_type, response_body, now):
        with self._raw_connect() as db:
            changed = db.execute(
                "UPDATE api_idempotency_records SET state='COMPLETED',status_code=%s,media_type=%s,"
                "response_body=%s,completed_at=%s WHERE scope_hash=%s AND request_hash=%s "
                "AND state='PENDING'",
                (status_code, media_type, response_body, now.isoformat(), scope_hash, request_hash),
            ).rowcount
            if changed != 1:
                raise RuntimeError("冪等性記録の所有権が失われました")

    def release(self, scope_hash: str, request_hash: str) -> None:
        with self._raw_connect() as db:
            db.execute(
                "DELETE FROM api_idempotency_records WHERE scope_hash=%s AND request_hash=%s "
                "AND state='PENDING'",
                (scope_hash, request_hash),
            )


def _record(row) -> IdempotencyRecord:
    body = row["response_body"]
    return IdempotencyRecord(
        row["request_hash"],
        row["state"],
        row["pending_until"],
        row["status_code"],
        row["media_type"],
        None if body is None else bytes(body),
    )


def _hash(*values: bytes) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def idempotent_route_class(store: IdempotencyStore):
    class IdempotentRoute(APIRoute):
        def get_route_handler(self):
            original = super().get_route_handler()
            route_path = self.path.encode()

            async def route_handler(request: Request) -> Response:
                key = request.headers.get("Idempotency-Key")
                if (
                    request.method != "POST"
                    or not request.url.path.startswith("/api/")
                    or key is None
                ):
                    return await original(request)
                if not KEY_PATTERN.fullmatch(key):
                    raise HTTPException(422, "Idempotency-Keyは1〜200文字の表示可能ASCIIにします")
                body = await request.body()
                auth_hash = hashlib.sha256(
                    request.headers.get("Authorization", "").encode()
                ).digest()
                scope_hash = _hash(route_path, key.encode(), auth_hash)
                request_hash = _hash(
                    request.method.encode(),
                    request.url.path.encode(),
                    request.url.query.encode(),
                    request.headers.get("content-type", "").encode(),
                    body,
                )
                now = datetime.now(UTC)
                outcome, record = store.claim(scope_hash, request_hash, now)
                if outcome == "MISMATCH":
                    raise HTTPException(409, "同じIdempotency-Keyが異なる要求に使われています")
                if outcome == "IN_PROGRESS":
                    raise HTTPException(409, "同じ要求を処理中です")
                if outcome == "REPLAY":
                    return Response(
                        content=record.response_body or b"",
                        status_code=record.status_code or 200,
                        media_type=record.media_type,
                        headers={"Idempotency-Replayed": "true"},
                    )
                try:
                    response = await original(request)
                except Exception:
                    store.release(scope_hash, request_hash)
                    raise
                payload = getattr(response, "body", None)
                cacheable = (
                    200 <= response.status_code < 300
                    and payload is not None
                    and len(payload) <= MAX_RESPONSE_BYTES
                )
                if cacheable:
                    media_type = response.media_type or "application/json"
                    store.complete(
                        scope_hash,
                        request_hash,
                        response.status_code,
                        media_type,
                        payload,
                        datetime.now(UTC),
                    )
                    response.headers["Idempotency-Replayed"] = "false"
                else:
                    store.release(scope_hash, request_hash)
                return response

            return route_handler

    return IdempotentRoute
