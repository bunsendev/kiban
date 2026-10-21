import gc
import io
import json
import logging
import os
import shutil
import sys
import zipfile
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.api.business_archive_intake import BusinessArchiveIntake
from portable.launcher import main as launcher
from portable.runtime.learning_backup import LearningBackup
from portable.runtime.paths import DataPaths


def archive():
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as z:
        z.writestr("arbitrary.csv", "倉庫,基準日,出荷日,JAN,数量\n"
                   "70301,2026-10-20,2026-10-20,4901234567894,2\n")
    return raw.getvalue()


def test_history_survives_copy_with_changed_mtimes_and_stable_ties(tmp_path):
    root = tmp_path / "original/Data"
    app = create_app(root)
    directory = root / "Analysis"
    for n in range(25):
        record = {
            "analysis_id": f"{n:064x}", "created_at": "2026-10-20T01:00:00+00:00",
            "status": "READY", "issues": [], "rows": {"auto_confirmed": n},
            "source_files": [{"center": "70301" if n % 2 else "70302"}],
        }
        (directory / f"{n:064x}.json").write_text(json.dumps(record), encoding="utf-8")
    (directory / ("f" * 64 + ".json")).write_text(json.dumps({
        **record, "analysis_id": "f" * 64, "created_at": None,
    }))
    client = TestClient(app, base_url="http://127.0.0.1")
    expected = client.get("/api/business-archives").json()
    assert len(expected) == 20
    assert expected[0]["analysis_id"] == f"{24:064x}"
    assert expected[0]["warehouses"] == ["70302"]
    assert expected[0]["created_at_source"] == "analysis"
    target = tmp_path / "other/Data"
    shutil.copytree(root, target)
    for i, p in enumerate(sorted((target / "Analysis").glob("*.json"), reverse=True)):
        os.utime(p, (1700000000 + i, 1700000000 + i))
    copied = TestClient(create_app(target), base_url="http://127.0.0.1")
    assert copied.get("/api/business-archives").json() == expected


def test_legacy_timestamp_fallback_is_verified_read_only_and_missing_is_explicit(tmp_path):
    root = tmp_path / "Data"
    client = TestClient(create_app(root), base_url="http://127.0.0.1")
    response = client.post("/api/business-archives", content=archive(),
                           headers={"Content-Type": "application/zip"})
    assert response.status_code == 201, response.text
    report = response.json()
    report_path = root / "Analysis" / (report["analysis_id"] + ".json")
    legacy = json.loads(report_path.read_text("utf-8"))
    del legacy["created_at"]
    report_path.write_text(json.dumps(legacy), encoding="utf-8")
    before = {p: p.read_bytes() for p in (root / "State/DailyAutoRuns").glob("*")}
    item = client.get("/api/business-archives").json()[0]
    assert item["created_at_source"] == "daily_run" and item["created_at"]
    assert all(p.read_bytes() == body for p, body in before.items())
    for p in before:
        p.unlink()
    item = client.get("/api/business-archives").json()[0]
    assert item["created_at"] is None and item["created_at_source"] == "unknown"
    assert not list((root / "State/DailyAutoRuns").glob("*"))


def test_reanalysis_preserves_original_creation_time_and_legacy_unknown(tmp_path):
    paths = DataPaths(tmp_path / "Data")
    paths.ensure()

    class Daily:
        def view(self, *_):
            return {}

    intake = BusinessArchiveIntake(paths, Daily())
    first = intake._ingest(archive(), {})
    second = intake._ingest(archive(), {})
    assert first["created_at"] == second["created_at"]
    path = paths.analysis / (first["analysis_id"] + ".json")
    second.pop("created_at")
    path.write_text(json.dumps(second), encoding="utf-8")
    assert "created_at" not in intake._ingest(archive(), {})


def stage_restore(root, tmp_path):
    source = tmp_path / "source/Data"
    (source / "State").mkdir(parents=True)
    (source / "State/learned.json").write_text('{"answer":"SYNTHETIC"}')
    backup = LearningBackup(source).create()
    (root / "State").mkdir(parents=True)
    (root / "State/keep-original.json").write_text('{"original":true}')
    LearningBackup(root).stage(backup, confirm=True)


@pytest.mark.parametrize("entry", ["launcher", "server"])
def test_real_startup_restores_before_own_logs_or_child_output_open(tmp_path, monkeypatch, entry):
    root = tmp_path / "installed/Data"
    stage_restore(root, tmp_path)
    logging_paths = []

    def open_log(path):
        # Opening these before the swap is the Windows failure being fixed.
        status = LearningBackup(root).status()
        assert status["status"] == "RESTORED" and not status["pending"]
        assert (root / "State/learned.json").exists()
        assert (Path(status["previous_data"]) / "State/keep-original.json").exists()
        with path.open("a", encoding="utf-8") as f:
            f.write("synthetic startup\n")
        logging_paths.append(path.name)

    monkeypatch.setattr(launcher, "setup_logging", open_log)
    if entry == "launcher":
        monkeypatch.setattr(launcher, "bundle_root", lambda: root.parent)
        monkeypatch.setattr(launcher, "SingleInstance", lambda _: nullcontext())
        monkeypatch.setattr(launcher, "setup_profile", lambda _: None)
        assert launcher.launch() == 0
        assert logging_paths == ["launcher.log"]
    else:
        monkeypatch.setattr(sys, "argv", ["test", "--server", "--data-root", str(root),
                                          "--port", "48150"])
        apps = []
        # Construct the real app but never start a server/listener.
        monkeypatch.setattr(launcher.uvicorn, "run", lambda app, **_: apps.append(app))
        assert launcher.main() == 0
        assert apps and logging_paths == ["api-server.log"]


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing semantics")
def test_open_windows_log_reproduces_access_denial_but_unopened_startup_restores(tmp_path):
    root = tmp_path / "installed/Data"
    stage_restore(root, tmp_path)
    (root / "Logs").mkdir()
    handler = logging.FileHandler(root / "Logs/launcher.log", encoding="utf-8")
    try:
        failed = LearningBackup(root).apply_pending()
        assert failed["status"] == "FAILED"
        assert "削除しない" in failed["guidance"]
        assert (root / "State/keep-original.json").exists()
    finally:
        handler.close()
    recovery = LearningBackup(root)
    # Recreate from source instead of relying on the generated ZIP filename.
    backup = LearningBackup(tmp_path / "source/Data").create()
    recovery.stage(backup, confirm=True)
    from portable.api.app import recover_data

    gc.collect()
    assert recover_data(root)["status"] == "RESTORED"
