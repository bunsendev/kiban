"""Phase 1RのPostgreSQL backup/restore安全条件。"""

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from forecast_provider.operations import database
from forecast_provider.operations.worker_config import postgres_dsn


class FakePostgresTools:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[0] == "pg_dump" and "--version" not in command:
            output = next(
                item.removeprefix("--file=")
                for item in command
                if item.startswith("--file=")
            )
            Path(output).write_bytes(b"PGDMP\x01synthetic-backup")
        stdout = "pg_dump (PostgreSQL) 17.6" if "--version" in command else "ok"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def test_backup_manifest_verify_and_restore_are_checksum_guarded(tmp_path, monkeypatch):
    tools = FakePostgresTools()
    monkeypatch.setattr(database.subprocess, "run", tools)
    dsn = "postgresql://backup-user:s%40fe-secret@db.example.test:5432/kiban?sslmode=require"

    manifest_path = database.backup_database(dsn, tmp_path / "backups")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive = manifest_path.parent / manifest["archive"]
    assert manifest["schema_version"] == database.SCHEMA_VERSION
    assert manifest["database"] == "kiban"
    assert manifest["size_bytes"] == archive.stat().st_size
    assert len(manifest["sha256"]) == 64
    assert "secret" not in manifest_path.read_text(encoding="utf-8")
    dump_call = tools.calls[0]
    assert all("secret" not in argument for argument in dump_call[0])
    assert dump_call[1]["env"]["PGPASSWORD"] == "s@fe-secret"
    assert dump_call[1]["env"]["PGSSLMODE"] == "require"

    assert database.verify_backup(manifest_path)["sha256"] == manifest["sha256"]
    with pytest.raises(ValueError, match="一致しません"):
        database.restore_database(dsn, manifest_path, "other")
    database.restore_database(dsn, manifest_path, "kiban")
    restore = tools.calls[-1]
    assert "--clean" in restore[0]
    assert "--if-exists" in restore[0]
    assert "--single-transaction" in restore[0]
    assert "--dbname=kiban" in restore[0]
    assert restore[1]["env"]["PGDATABASE"] == "kiban"

    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        database.verify_backup(manifest_path)


def test_connection_settings_reject_unsupported_dsn():
    with pytest.raises(ValueError, match="postgresql URI"):
        database.connection_settings("dbname=kiban user=owner")
    with pytest.raises(ValueError, match="未対応"):
        database.connection_settings("postgresql://db/kiban?application_name=unsafe")


def test_worker_reads_postgres_dsn_from_secret_file(tmp_path):
    secret = tmp_path / "postgres-dsn"
    secret.write_text("postgresql://worker:secret@postgres/kiban\n", encoding="utf-8")
    args = argparse.Namespace(
        sqlite=None,
        postgres_dsn=None,
        postgres_dsn_file=secret,
    )
    assert postgres_dsn(args) == "postgresql://worker:secret@postgres/kiban"
