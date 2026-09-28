"""現場PCの更新確認。通信障害を業務処理から分離し、結果を追記保存する。"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .github_release import GitHubReleaseUpdateProvider
from .manifest import CHANNELS, version_key

CHECK_INTERVAL = timedelta(hours=6)


class UpdateCheckStore:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("""CREATE TABLE IF NOT EXISTS update_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checked_at TEXT NOT NULL,
            trigger TEXT NOT NULL,
            current_version TEXT NOT NULL,
            available_version TEXT,
            status TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '[]'
        )""")
        return db

    def latest(self) -> dict | None:
        with self._connect() as db:
            row = db.execute("""SELECT checked_at, trigger, current_version,
                available_version, status, notes FROM update_checks
                ORDER BY id DESC LIMIT 1""").fetchone()
        if row is None:
            return None
        return dict(zip(("checked_at", "trigger", "current_version",
                         "available_version", "status", "notes"),
                        (*row[:5], json.loads(row[5])), strict=True))

    def append(self, *, trigger: str, current_version: str,
               available_version: str | None, status: str,
               notes: tuple[str, ...] = ()) -> dict:
        checked_at = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("""INSERT INTO update_checks
                (checked_at, trigger, current_version, available_version, status, notes)
                VALUES (?, ?, ?, ?, ?, ?)""",
                       (checked_at, trigger, current_version, available_version,
                        status, json.dumps(notes, ensure_ascii=False)))
        return self.latest()


class UpdateCheckService:
    def __init__(self, *, store: UpdateCheckStore, current_version: str,
                 channel: str, public_key_path: Path,
                 provider: GitHubReleaseUpdateProvider | None = None):
        version_key(current_version)
        if channel not in CHANNELS:
            raise ValueError("UPDATE_CHANNEL_INVALID")
        self.store = store
        self.current_version = current_version
        self.channel = channel
        self.public_key_path = public_key_path
        self.provider = provider or GitHubReleaseUpdateProvider()

    def status(self) -> dict:
        return {"current_version": self.current_version, "channel": self.channel,
                "public_key_configured": self.public_key_path.is_file(),
                "last_check": self.store.latest()}

    def check(self, *, trigger: str, force: bool = False) -> dict:
        if trigger not in {"STARTUP", "END_OF_DAY", "MANUAL"}:
            raise ValueError("UPDATE_TRIGGER_INVALID")
        latest = self.store.latest()
        if not force and latest is not None and latest["current_version"] == self.current_version:
            checked = datetime.fromisoformat(latest["checked_at"])
            if datetime.now(UTC) - checked < CHECK_INTERVAL:
                return self.status()
        if not self.public_key_path.is_file():
            self.store.append(trigger=trigger, current_version=self.current_version,
                              available_version=None, status="UNCONFIGURED")
            return self.status()
        try:
            public_pem = self.public_key_path.read_bytes()
            if len(public_pem) > 8192:
                raise ValueError("UPDATE_KEY_TOO_LARGE")
            offer = self.provider.check(current_version=self.current_version,
                                        channel=self.channel, public_pem=public_pem)
            self.store.append(
                trigger=trigger, current_version=self.current_version,
                available_version=offer.manifest.version if offer else None,
                status=offer.status if offer else "NO_RELEASE",
                notes=offer.manifest.notes if offer else (),
            )
        except Exception:
            # 更新側の通信・形式異常を業務画面に伝播させない。例外詳細は保持しない。
            self.store.append(trigger=trigger, current_version=self.current_version,
                              available_version=None, status="CHECK_FAILED")
        return self.status()
