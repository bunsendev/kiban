"""現場設定変更の直前にSQLiteの一貫したローカルBackupを作る。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


class LocalSettingBackup:
    def __init__(self, database: Path, backup_root: Path):
        self.database = database
        self.backup_root = backup_root

    def create(self) -> Path:
        if self.database.is_symlink() or self.backup_root.is_symlink():
            raise ValueError("LOCAL_BACKUP_PATH_INVALID")
        if not self.database.is_file():
            raise ValueError("LOCAL_BACKUP_SOURCE_MISSING")
        self.backup_root.mkdir(parents=True, exist_ok=True)
        identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
        final = self.backup_root / f"settings-{identifier}.sqlite3"
        temporary = self.backup_root / f".{identifier}.tmp"
        manifest_temporary = self.backup_root / f".{identifier}.json.tmp"
        try:
            with closing(sqlite3.connect(self.database)) as source:
                with closing(sqlite3.connect(temporary)) as target:
                    source.backup(target)
            with closing(sqlite3.connect(temporary)) as check:
                if check.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("LOCAL_BACKUP_INTEGRITY_FAILED")
            digest = hashlib.sha256()
            with temporary.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            os.replace(temporary, final)
            manifest = {
                "format": "field-setting-backup-v1", "sha256": digest.hexdigest(),
                "created_at": datetime.now(UTC).isoformat(),
                "database": final.name,
            }
            manifest_path = final.with_suffix(".json")
            manifest_temporary.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            os.replace(manifest_temporary, manifest_path)
            return final
        finally:
            temporary.unlink(missing_ok=True)
            manifest_temporary.unlink(missing_ok=True)
