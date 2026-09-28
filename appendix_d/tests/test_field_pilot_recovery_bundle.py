"""復旧ZIPの対象制限、完全性、互換性、展開を人工データで検証する。"""

import hashlib
import json
import sqlite3
import zipfile

import pytest

from forecast_provider.field_pilot.recovery_bundle import (
    create_bundle,
    stage_bundle,
    verify_bundle,
)


def _source(tmp_path):
    data = tmp_path / "Data"
    (data / "Config").mkdir(parents=True)
    (data / "LocalSettings").mkdir()
    (data / "Inbox").mkdir()
    (data / "Config" / "pilot-settings.json").write_text(
        '{"mode":"SHADOW","read_only":true}', encoding="utf-8",
    )
    (data / "Config" / "inbox-policy.json").write_text('{"required":[]}', encoding="utf-8")
    (data / "Config" / "pilot.env").write_text("PASSWORD=do-not-export", encoding="utf-8")
    (data / "Inbox" / "raw.csv").write_text("private,row", encoding="utf-8")
    for relative in ("LocalSettings/field-settings.sqlite3", "Inbox/inbox.sqlite3"):
        with sqlite3.connect(data / relative) as db:
            db.execute("CREATE TABLE setting_version (version TEXT)")
            db.execute("INSERT INTO setting_version VALUES ('v1')")
    return data


def _rewrite(source, target, *, replacement=None, extra=None):
    with zipfile.ZipFile(source) as existing, zipfile.ZipFile(target, "w") as output:
        for name in existing.namelist():
            output.writestr(name, replacement if name == "config/pilot-settings.json"
                            and replacement is not None else existing.read(name))
        if extra:
            output.writestr(extra, b"unexpected")


def test_settings_bundle_excludes_credentials_raw_and_postgres(tmp_path):
    data = _source(tmp_path)
    bundle = tmp_path / "settings.zip"
    result = create_bundle(data, bundle, mode="SETTINGS")
    assert result["mode"] == "SETTINGS"
    assert verify_bundle(bundle) == result
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        assert "config/pilot.env" not in names
        assert "database/postgres.dump" not in names
        assert "learning/raw.csv" not in names
        assert "settings/field-settings.sqlite3" in names
    stage = tmp_path / "staged"
    assert stage_bundle(bundle, stage) == result
    assert json.loads((stage / "manifest.json").read_text(encoding="utf-8")) == result
    assert (stage / "learning" / "inbox.sqlite3").is_file()
    assert not (stage / "config" / "pilot.env").exists()


def test_full_bundle_requires_and_verifies_postgres_dump(tmp_path):
    data = _source(tmp_path)
    dump = tmp_path / "postgres.dump"
    dump.write_bytes(b"PGDMP" + b"test" * 100)
    bundle = tmp_path / "full.zip"
    with pytest.raises(ValueError, match="RECOVERY_DATABASE_REQUIRED"):
        create_bundle(data, bundle, mode="FULL")
    result = create_bundle(data, bundle, mode="FULL", postgres_dump=dump)
    assert result["files"]["database/postgres.dump"]["size"] == dump.stat().st_size
    assert verify_bundle(bundle)["mode"] == "FULL"


def test_modified_and_unlisted_entries_are_rejected_before_staging(tmp_path):
    data = _source(tmp_path)
    bundle = tmp_path / "settings.zip"
    create_bundle(data, bundle, mode="SETTINGS")
    changed = tmp_path / "changed.zip"
    _rewrite(bundle, changed, replacement=b"{}")
    with pytest.raises(ValueError, match=r"RECOVERY_(MANIFEST|HASH)_"):
        verify_bundle(changed)
    traversal = tmp_path / "traversal.zip"
    _rewrite(bundle, traversal, extra="../outside.txt")
    with pytest.raises(ValueError, match="RECOVERY_ARCHIVE_ENTRIES_INVALID"):
        stage_bundle(traversal, tmp_path / "should-not-exist")
    assert not (tmp_path / "outside.txt").exists()


def test_incompatible_version_and_corrupt_sqlite_are_rejected(tmp_path):
    data = _source(tmp_path)
    bundle = tmp_path / "settings.zip"
    create_bundle(data, bundle, mode="SETTINGS")
    incompatible = tmp_path / "incompatible.zip"
    with zipfile.ZipFile(bundle) as original, zipfile.ZipFile(incompatible, "w") as output:
        for name in original.namelist():
            content = original.read(name)
            if name == "manifest.json":
                manifest = json.loads(content)
                manifest["application_version"] = "999.0.0"
                content = json.dumps(manifest).encode()
            output.writestr(name, content)
    with pytest.raises(ValueError, match="RECOVERY_VERSION_INCOMPATIBLE"):
        verify_bundle(incompatible)
    (data / "Inbox" / "inbox.sqlite3").write_bytes(b"corrupt")
    with pytest.raises(sqlite3.DatabaseError):
        create_bundle(data, tmp_path / "bad.zip", mode="SETTINGS")


def test_sqlite_wal_rows_are_included_in_snapshot(tmp_path):
    data = _source(tmp_path)
    path = data / "Inbox" / "inbox.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("INSERT INTO setting_version VALUES ('from-wal')")
        db.commit()
        bundle = tmp_path / "settings.zip"
        create_bundle(data, bundle, mode="SETTINGS")
    stage_bundle(bundle, tmp_path / "stage")
    with sqlite3.connect(tmp_path / "stage" / "learning" / "inbox.sqlite3") as restored:
        rows = restored.execute("SELECT version FROM setting_version ORDER BY version").fetchall()
        assert rows == [
            ("from-wal",), ("v1",),
        ]


def test_valid_hash_with_non_shadow_settings_is_rejected_before_application(tmp_path):
    data = _source(tmp_path)
    bundle = tmp_path / "settings.zip"
    create_bundle(data, bundle, mode="SETTINGS")
    unsafe = tmp_path / "unsafe.zip"
    payload = b'{"mode":"ADVISORY","read_only":false}'
    with zipfile.ZipFile(bundle) as original, zipfile.ZipFile(unsafe, "w") as output:
        manifest = json.loads(original.read("manifest.json"))
        manifest["files"]["config/pilot-settings.json"] = {
            "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload),
        }
        for name in original.namelist():
            content = json.dumps(manifest).encode() if name == "manifest.json" else (
                payload if name == "config/pilot-settings.json" else original.read(name)
            )
            output.writestr(name, content)
    with pytest.raises(ValueError, match="RECOVERY_SETTINGS_INVALID"):
        stage_bundle(unsafe, tmp_path / "stage")


def test_release_fingerprint_blocks_a_different_build(tmp_path):
    data = _source(tmp_path)
    bundle = tmp_path / "settings.zip"
    create_bundle(data, bundle, mode="SETTINGS", release_fingerprint="release-a")
    assert verify_bundle(bundle, release_fingerprint="release-a")["mode"] == "SETTINGS"
    with pytest.raises(ValueError, match="RECOVERY_RELEASE_INCOMPATIBLE"):
        stage_bundle(bundle, tmp_path / "stage", release_fingerprint="release-b")
    assert not (tmp_path / "stage").exists()
