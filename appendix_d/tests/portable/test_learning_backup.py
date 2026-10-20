import gc
import io
import json
import sqlite3
import uuid
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.runtime.learning_backup import LearningBackup, atomic


def seed(root):
    (root / "State").mkdir(parents=True, exist_ok=True)
    (root / "State/rules.json").write_text('{"learned":"人工確認済み"}', encoding="utf-8")
    (root / "State/installation.json").write_text('{"device":"source"}', encoding="utf-8")
    (root / "State/feedback-admin-session.json").write_text('{"secret":"never export"}')
    db = sqlite3.connect(root / "State/learning.sqlite3")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS learning (answer TEXT)")
    db.execute("INSERT INTO learning VALUES ('SYNTHETIC_CONFIRMED')")
    db.commit()
    return db


def test_live_wal_backup_and_reinstall_elsewhere(tmp_path):
    root = tmp_path / "old/Data"
    db = seed(root)
    source = LearningBackup(root)
    backup = source.create()
    with zipfile.ZipFile(backup) as z:
        assert "State/installation.json" not in z.namelist()
        assert "State/feedback-admin-session.json" not in z.namelist()
        assert not any(n.endswith(("-wal", "-shm")) for n in z.namelist())
    db.close()
    new = tmp_path / "reinstalled/Data"
    (new / "State").mkdir(parents=True)
    (new / "State/installation.json").write_text('{"device":"target"}')
    (new / "State/current-only.json").write_text("{}")
    recovery = LearningBackup(new)
    recovery.stage(backup, confirm=True)
    # Staging does not mutate live data.
    assert (new / "State/current-only.json").exists()
    result = recovery.apply_pending()
    assert result["status"] == "RESTORED"
    assert not (new / "State/current-only.json").exists()
    assert (Path(result["previous_data"]) / "State/current-only.json").exists()
    assert json.loads((new / "State/installation.json").read_text())["device"] == "target"
    conn = sqlite3.connect(new / "State/learning.sqlite3")
    assert conn.execute("SELECT answer FROM learning").fetchone() == ("SYNTHETIC_CONFIRMED",)
    conn.close()
    assert not recovery.status()["pending"]


def test_tamper_missing_future_and_unsafe_zip_rejected(tmp_path):
    db = seed(tmp_path / "Data")
    backup = LearningBackup(tmp_path / "Data").create()
    db.close()
    with zipfile.ZipFile(backup) as z:
        content = {n: z.read(n) for n in z.namelist()}
    recovery = LearningBackup(tmp_path / "other/Data")
    for mode in ("tamper", "missing", "future", "path", "reserved", "collision"):
        c = dict(content)
        if mode == "tamper":
            c["State/rules.json"] = b"different"
        elif mode == "missing":
            del c["State/rules.json"]
        elif mode == "future":
            manifest = json.loads(c["backup-manifest.json"])
            manifest["app_version"] = "99.0.0-pilot.999"
            c["backup-manifest.json"] = json.dumps(manifest).encode()
        elif mode == "path":
            c["../outside.txt"] = b"bad"
        elif mode == "reserved":
            c["State/NUL"] = b"bad"
        else:
            c["State/Rules.json"] = b"bad"
        p = tmp_path / (mode + ".zip")
        with zipfile.ZipFile(p, "w") as z:
            for n, b in c.items():
                z.writestr(n, b)
        with pytest.raises(ValueError):
            recovery.inspect(p)


def test_legacy_confirmation_and_corrupt_database_preserve_current(tmp_path):
    data = tmp_path / "Data"
    data.mkdir()
    (data / "keep.txt").write_text("current")
    legacy = tmp_path / "Data-backup.zip"
    with zipfile.ZipFile(legacy, "w") as z:
        z.writestr("Data/State/learning.sqlite3", b"not a sqlite database")
        z.writestr("Data/State/installation.json", '{"device":"other"}')
    recovery = LearningBackup(data)
    with pytest.raises(ValueError):
        recovery.stage(legacy, confirm=True)
    recovery.stage(legacy, confirm=True, allow_legacy=True)
    result = recovery.apply_pending()
    assert result["status"] == "FAILED"
    assert (data / "keep.txt").read_text() == "current"


def test_pending_hash_and_cancel(tmp_path):
    db = seed(tmp_path / "Data")
    r = LearningBackup(tmp_path / "Data")
    p = r.create()
    db.close()
    r.stage(p, confirm=True)
    pending = json.loads((r.work / "pending.json").read_text())
    (r.work / pending["archive"]).write_bytes(b"corrupt")
    assert r.apply_pending()["status"] == "FAILED"
    assert (tmp_path / "Data/State/rules.json").exists()
    r.stage(p, confirm=True)
    r.cancel()
    assert not r.status()["pending"]


def test_interrupted_swap_rolls_back(tmp_path):
    data = tmp_path / "Data"
    db = seed(data)
    db.close()
    r = LearningBackup(data)
    tid = str(uuid.uuid4())
    tx = r.work / tid
    tx.mkdir()
    data.rename(tx / "previous-Data")
    atomic(r.work / "swap.json", {"transaction": tid})
    assert r.apply_pending()["status"] == "INTERRUPTED_ROLLED_BACK"
    assert (data / "State/rules.json").exists()


def test_api_preview_stage_write_freeze_cancel_and_startup_restore(tmp_path):
    data = tmp_path / "Data"
    app = create_app(data)
    client = TestClient(app, base_url="http://127.0.0.1")
    (data / "State/synthetic-rules.json").write_text('{"corrected":true}')
    backup = client.post("/api/learning-backup/create")
    assert backup.status_code == 200
    assert client.get("/learning-backup").status_code == 200
    assert client.get("/field/assets/learning-backup.js").status_code == 200
    app.state.active = 1
    assert client.post("/api/learning-backup/create").status_code == 409
    app.state.active = 0
    preview = client.post("/api/learning-backup/preview", content=backup.content).json()
    payload = {"id": preview["id"], "confirm": True}
    (data / "State/synthetic-rules.json").write_text('{"corrected":false}')
    assert client.post("/api/learning-backup/restore", json=payload).status_code == 200
    assert client.post("/api/operations/send", json={}).status_code == 409
    assert client.post("/api/learning-backup/cancel").status_code == 200
    assert client.post("/api/learning-backup/restore", json=payload).status_code == 200
    client.close()
    del app
    gc.collect()
    restored = TestClient(create_app(data), base_url="http://127.0.0.1")
    assert restored.get("/api/learning-backup/status").json()["status"] == "RESTORED"
    assert json.loads((data / "State/synthetic-rules.json").read_text())["corrected"]


def test_db_backup_manifest_contains_committed_wal_rows(tmp_path):
    db = seed(tmp_path / "Data")
    r = LearningBackup(tmp_path / "Data")
    raw = r.create().read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        p = tmp_path / "copied.sqlite3"
        p.write_bytes(z.read("State/learning.sqlite3"))
    copy = sqlite3.connect(p)
    assert copy.execute("SELECT COUNT(*) FROM learning").fetchone()[0] == 1
    copy.close()
    db.close()


def test_actual_exclusion_learning_survives_new_installation(tmp_path):
    from portable.api.product_exclusions import ProductExclusions
    from portable.runtime.paths import DataPaths

    source = DataPaths(tmp_path / "source/Data")
    source.ensure()
    rules = ProductExclusions(source)
    rules.save(
        {
            "actor": "人工確認者",
            "products": [
                {
                    "jan": "4901234567894",
                    "exclude": True,
                    "reason": "人工対象外の確認",
                    "product_name": "人工商品",
                }
            ],
        }
    )
    p = LearningBackup(source.root).create()
    target = DataPaths(tmp_path / "new-install/Data")
    target.ensure()
    r = LearningBackup(target.root)
    r.stage(p, confirm=True)
    gc.collect()
    assert r.apply_pending()["status"] == "RESTORED"
    restored = ProductExclusions(target).list()
    assert len(restored) == 1 and restored[0]["exclude"] == 1
    assert restored[0]["reason"] == "人工対象外の確認"


def test_interrupted_swap_with_launcher_recreated_data_rolls_back(tmp_path):
    data = tmp_path / "Data"
    db = seed(data)
    db.close()
    r = LearningBackup(data)
    tid = str(uuid.uuid4())
    tx = r.work / tid
    tx.mkdir()
    (tx / "new-Data").mkdir()
    data.rename(tx / "previous-Data")
    (data / "State").mkdir(parents=True)
    atomic(r.work / "swap.json", {"transaction": tid})
    assert r.apply_pending()["status"] == "INTERRUPTED_ROLLED_BACK"
    assert (data / "State/rules.json").exists()


def test_failed_swap_rolls_back_original(tmp_path, monkeypatch):
    db = seed(tmp_path / "Data")
    r = LearningBackup(tmp_path / "Data")
    p = r.create()
    db.close()
    r.stage(p, confirm=True)
    original = Path.rename

    def fail_new(path, target):
        if path.name == "new-Data":
            raise PermissionError("synthetic locked directory")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", fail_new)
    assert r.apply_pending()["status"] == "FAILED"
    assert (tmp_path / "Data/State/rules.json").exists()


def test_failed_rollback_keeps_journal_and_refuses_empty_startup(tmp_path, monkeypatch):
    db = seed(tmp_path / "Data")
    r = LearningBackup(tmp_path / "Data")
    p = r.create()
    db.close()
    r.stage(p, confirm=True)
    original = Path.rename

    def fail_both(path, target):
        if path.name in {"new-Data", "previous-Data"}:
            raise PermissionError("synthetic locked directory")
        return original(path, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", fail_both)
        with pytest.raises(OSError):
            r.apply_pending()
    assert not (tmp_path / "Data").exists()
    assert (r.work / "swap.json").exists()
    assert r.apply_pending()["status"] == "INTERRUPTED_ROLLED_BACK"
    assert (tmp_path / "Data/State/rules.json").exists()


def test_incompatible_schema_fails_before_replacing_current_data(tmp_path):
    source = tmp_path / "old/Data"
    (source / "State").mkdir(parents=True)
    db = sqlite3.connect(source / "State/runs.sqlite3")
    db.execute("CREATE TABLE runs (incompatible_column TEXT)")
    db.commit()
    db.close()
    backup = LearningBackup(source).create()
    target = tmp_path / "installed/Data"
    current = create_app(target)
    (target / "State/keep.json").write_text('{"keep":true}')
    recovery = LearningBackup(target)
    recovery.stage(backup, confirm=True)
    del current
    gc.collect()
    restarted = TestClient(create_app(target), base_url="http://127.0.0.1")
    status = restarted.get("/api/learning-backup/status").json()
    assert status["status"] == "FAILED"
    assert (target / "State/keep.json").is_file()
    assert not status["pending"]


def test_long_windows_data_path_sqlite_backup(tmp_path):
    from portable.api.product_exclusions import ProductExclusions
    from portable.runtime.paths import DataPaths

    paths = DataPaths(tmp_path / ("long-" * 20) / ("nested-" * 20) / "Data")
    paths.ensure()
    ProductExclusions(paths)
    recovery = LearningBackup(paths.root)
    info = recovery.inspect(recovery.create())
    assert info["files"] >= 1
