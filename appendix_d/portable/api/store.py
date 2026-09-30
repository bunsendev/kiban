"""PoC-only SQLite run ledger; production PostgreSQL remains unchanged."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunStore:
    def __init__(self, path: Path):
        self.path = path
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    result_sha256 TEXT,
                    app_version TEXT NOT NULL,
                    provider_version TEXT NOT NULL,
                    result_path TEXT,
                    error_code TEXT
                )"""
            )
            db.execute(
                "UPDATE runs SET status='INTERRUPTED', finished_at=?, "
                "error_code='PORTABLE-RUN-INTERRUPTED' WHERE status='RUNNING'",
                (_now(),),
            )

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def start(self, run_id: str, input_sha: str, app_version: str, provider_version: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO runs(run_id,started_at,status,input_sha256,"
                "app_version,provider_version) "
                "VALUES(?,?,'RUNNING',?,?,?)",
                (run_id, _now(), input_sha, app_version, provider_version),
            )

    def finish(
        self,
        run_id: str,
        *,
        result_sha: str | None = None,
        result_path: str | None = None,
        error_code: str | None = None,
    ) -> None:
        status = "SUCCESS" if result_sha else "FAILED"
        with self._connect() as db:
            db.execute(
                "UPDATE runs SET status=?, finished_at=?, result_sha256=?, result_path=?, "
                "error_code=? WHERE run_id=? AND status='RUNNING'",
                (status, _now(), result_sha, result_path, error_code, run_id),
            )

    def get(self, run_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 50").fetchall()
        return [dict(row) for row in rows]
