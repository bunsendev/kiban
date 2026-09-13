"""Phase 2D PostgreSQL隔離リカバリ訓練。"""

import json

import pytest

from forecast_provider.operations.db_archive import ConnectionSettings
from forecast_provider.operations.recovery import runner
from forecast_provider.operations.recovery.contracts import DatabaseFingerprint
from forecast_provider.operations.recovery.scratch import scratch_connection


def _connection(database: str = "kiban") -> ConnectionSettings:
    return ConnectionSettings(
        database=database,
        environment={
            "PGHOST": "private.example.test",
            "PGDATABASE": database,
            "PGUSER": "secret-user",
            "PGPASSWORD": "top-secret",
        },
    )


def _install_successful_dependencies(monkeypatch, tmp_path):
    source = _connection()
    fingerprint = DatabaseFingerprint("a" * 64, 23, 17)
    manifest = tmp_path / "private-backup-location" / "backup.manifest.json"
    archive = manifest.with_suffix(".dump")
    calls: list[str] = []
    monkeypatch.setattr(runner, "connection_settings", lambda _dsn: source)
    monkeypatch.setattr(runner, "generate_scratch_name", lambda: "kiban_drill_012345abcdef")
    monkeypatch.setattr(runner, "database_fingerprint", lambda _connection: fingerprint)
    monkeypatch.setattr(runner, "backup_database", lambda _dsn, _root: manifest)
    monkeypatch.setattr(runner, "verify_backup", lambda _path: {"sha256": "b" * 64})
    monkeypatch.setattr(runner, "_verified_archive", lambda _path: (archive, {}))
    monkeypatch.setattr(runner, "create_scratch", lambda *_: calls.append("create"))
    monkeypatch.setattr(runner, "restore_scratch", lambda *_: calls.append("restore"))
    monkeypatch.setattr(runner, "drop_scratch", lambda *_: calls.append("drop"))
    return calls


def test_drill_passes_all_checks_and_publishes_sanitized_report(tmp_path, monkeypatch):
    calls = _install_successful_dependencies(monkeypatch, tmp_path)
    secret_dsn = "postgresql://secret-user:top-secret@private.example.test/kiban"

    result = runner.run_recovery_drill(
        secret_dsn, tmp_path / "private-backup-location", tmp_path / "reports"
    )

    assert result.outcome == "DRILL_PASSED"
    assert calls == ["create", "restore", "drop"]
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert set(report["checks"].values()) == {"PASSED"}
    assert report["source_fingerprint_sha256"] == "a" * 64
    assert report["restored_fingerprint_sha256"] == "a" * 64
    assert report["relation_count"] == 23
    serialized = result.report_path.read_text(encoding="utf-8")
    for forbidden in (
        "top-secret",
        "secret-user",
        "private.example.test",
        "kiban_drill_012345abcdef",
        "private-backup-location",
    ):
        assert forbidden not in serialized
    assert result.report_path.stem == result.report_sha256


def test_drill_drops_scratch_and_reports_only_failure_class(tmp_path, monkeypatch):
    calls = _install_successful_dependencies(monkeypatch, tmp_path)

    def fail_restore(*_args):
        raise RuntimeError("top-secret private.example.test")

    monkeypatch.setattr(runner, "restore_scratch", fail_restore)
    result = runner.run_recovery_drill(
        "postgresql://secret-user:top-secret@private.example.test/kiban",
        tmp_path / "backups",
        tmp_path / "reports",
    )

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.outcome == "DRILL_FAILED"
    assert calls == ["create", "drop"]
    assert report["checks"]["restore_completed"] == "FAILED"
    assert report["checks"]["scratch_removed"] == "PASSED"
    assert report["failure_stage"] == "restore_completed"
    assert report["failure_type"] == "RuntimeError"
    assert "top-secret" not in result.report_path.read_text(encoding="utf-8")


def test_scratch_database_name_is_internal_and_distinct():
    source = _connection()
    target = scratch_connection(source, "kiban_drill_012345abcdef")
    assert target.database == "kiban_drill_012345abcdef"
    assert target.environment["PGDATABASE"] == target.database

    with pytest.raises(ValueError, match="内部生成"):
        scratch_connection(source, "production")
    with pytest.raises(ValueError, match="分離"):
        scratch_connection(_connection("kiban_drill_012345abcdef"), target.database)
