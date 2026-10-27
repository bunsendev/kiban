"""Append-only local quality evidence; originals and operational ledgers are untouched."""

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(UTC).isoformat()


class QualityStore:
    def __init__(self, paths):
        self.path = paths.state / "data-quality.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS quality_meta (version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO quality_meta VALUES(1);
                CREATE TABLE IF NOT EXISTS quality_records (
                    kind TEXT NOT NULL, id TEXT NOT NULL, scope TEXT NOT NULL,
                    created_at TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(kind,id));
                CREATE INDEX IF NOT EXISTS quality_scope ON quality_records(kind,scope);
                CREATE TABLE IF NOT EXISTS quality_sources (
                    check_id TEXT NOT NULL, sha TEXT NOT NULL, PRIMARY KEY(check_id,sha));
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def put(self, kind, identifier, scope, body):
        raw = canonical(body)
        with self.connect() as db:
            previous = db.execute(
                "SELECT body FROM quality_records WHERE kind=? AND id=?", (kind, identifier)
            ).fetchone()
            if previous and previous[0] != raw:
                raise ValueError("同じ品質履歴の内容を上書きできません")
            db.execute(
                "INSERT OR IGNORE INTO quality_records VALUES(?,?,?,?,?)",
                (kind, identifier, scope, now(), raw),
            )
            if kind == "check":
                db.executemany(
                    "INSERT OR IGNORE INTO quality_sources VALUES(?,?)",
                    [(identifier, f["sha256"]) for f in body.get("source_files", [])],
                )
        return self.get(kind, identifier)

    def get(self, kind, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{64}", identifier):
            raise ValueError("品質履歴IDを確認してください")
        with self.connect() as db:
            row = db.execute(
                "SELECT body,created_at FROM quality_records WHERE kind=? AND id=?",
                (kind, identifier),
            ).fetchone()
        if row is None:
            raise ValueError("品質履歴が見つかりません")
        body = json.loads(row[0])
        if digest(body) != identifier:
            raise ValueError("品質履歴の整合性を確認できません")
        return body | {"id": identifier, "recorded_at": row[1]}

    def list(self, kind, scope=None, limit=100):
        query = "SELECT id FROM quality_records WHERE kind=?"
        args = [kind]
        if scope is not None:
            query += " AND scope=?"
            args.append(scope)
        with self.connect() as db:
            ids = db.execute(query + " ORDER BY rowid DESC LIMIT ?", (*args, limit)).fetchall()
        return [self.get(kind, row[0]) for row in ids]

    def save(self, kind, scope, body):
        return self.put(kind, digest(body), scope, body)

    def covering(self, identifier):
        with self.connect() as db:
            if not db.execute(
                "SELECT 1 FROM quality_sources WHERE check_id=?", (identifier,)
            ).fetchone():
                return self.get("check", identifier)
            row = db.execute(
                """
                SELECT r.id FROM quality_records r WHERE r.kind='check' AND NOT EXISTS (
                    SELECT 1 FROM quality_sources s WHERE s.check_id=? AND NOT EXISTS (
                        SELECT 1 FROM quality_sources n WHERE n.check_id=r.id AND n.sha=s.sha))
                ORDER BY r.rowid DESC LIMIT 1
            """,
                (identifier,),
            ).fetchone()
        return self.get("check", row[0] if row else identifier)
