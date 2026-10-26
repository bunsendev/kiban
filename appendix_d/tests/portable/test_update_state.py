"""Real concurrent metadata writers and failure paths must not escape startup."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_operations_delivery import signed_release

from portable.api.app import create_app
from portable.runtime import release_update, update_state
from portable.runtime.release_update import ReleaseUpdate


def test_concurrent_update_instances_use_distinct_tempfiles(tmp_path):
    barrier = threading.Barrier(8)

    def save(number):
        updater = ReleaseUpdate(tmp_path)
        barrier.wait(timeout=5)
        for attempt in range(15):
            result = updater.record(status="CURRENT", writer=number, attempt=attempt)
            assert result["status"] == "CURRENT"
            value = updater.status()
            assert value["status"] == "CURRENT" and isinstance(value["writer"], int)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save, range(8)))
    assert json.loads((tmp_path / "Updates/status.json").read_text())["status"] == "CURRENT"
    assert not list((tmp_path / "Updates").glob("*.tmp"))


def test_transient_windows_replace_failure_is_retried_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    replace = update_state.os.replace
    attempts = []

    def busy(source, target):
        attempts.append(source)
        if len(attempts) < 3:
            raise PermissionError("synthetic lock")
        replace(source, target)

    monkeypatch.setattr(update_state.os, "replace", busy)
    update_state.write_state(path, {"status": "CURRENT"})
    assert len(attempts) == 3
    assert json.loads(path.read_text()) == {"status": "CURRENT"}
    assert not list(tmp_path.glob("*.tmp"))


def test_check_write_failure_preserves_disk_and_blocks_update_until_retry(tmp_path, monkeypatch):
    key = tmp_path / "public.pem"
    key.write_bytes(b"synthetic")
    updater = ReleaseUpdate(tmp_path, key_path=key, fetch=lambda *_: b"[]")
    updater.record(status="AVAILABLE", version="0.6.0-pilot.999")
    old = (updater.work / "status.json").read_bytes()
    write = release_update.write_state

    def denied(*_):
        raise PermissionError("private-path synthetic-sensitive-value")

    monkeypatch.setattr(release_update, "write_state", denied)
    result = updater.check()
    assert result == {"status": "CHECK_FAILED", "reason": "STATE_SAVE_FAILED", "retryable": True}
    assert updater.status() == result
    assert (updater.work / "status.json").read_bytes() == old
    assert "private-path" not in json.dumps(result)
    with pytest.raises(ValueError, match="更新を確認"):
        updater.stage()
    monkeypatch.setattr(release_update, "write_state", write)
    assert updater.check() == {"status": "NO_RELEASE"}
    assert updater.status() == {"status": "NO_RELEASE"}


def test_status_corruption_is_recoverable(tmp_path):
    updater = ReleaseUpdate(tmp_path)
    (updater.work / "status.json").write_text("{")
    assert updater.status()["reason"] == "STATE_READ_FAILED"
    assert updater.record(status="CURRENT") == {"status": "CURRENT"}
    assert updater.status() == {"status": "CURRENT"}


def test_staging_write_failure_never_requests_application(tmp_path, monkeypatch):
    updater, *_ = signed_release(tmp_path)
    assert updater.check()["status"] == "AVAILABLE"
    write = release_update.write_state

    def denied_status(path, value):
        if path.name == "status.json":
            raise PermissionError("synthetic lock")
        write(path, value)

    monkeypatch.setattr(release_update, "write_state", denied_status)
    with pytest.raises(ValueError, match="更新状態を保存"):
        updater.stage()
    assert updater.status()["reason"] == "STATE_SAVE_FAILED"
    assert not (tmp_path / "App").exists()


def test_unexpected_background_failure_is_visible_without_thread_exception(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.delenv("PORTABLE_SMOKE", raising=False)
    app = create_app(tmp_path / "Data")
    called = threading.Event()
    monkeypatch.setattr(app.state.delivery, "send", lambda: {})

    def fail():
        called.set()
        raise OSError("synthetic backend failure")

    monkeypatch.setattr(app.state.updates, "check", fail)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert called.wait(timeout=5)
        # Wait for this worker's handler, rather than racing the Event.set().
        app.state.operations_thread.join(timeout=2)
        assert client.get("/api/operations/status").json()["update"] == {
            "status": "CHECK_FAILED", "reason": "BACKGROUND_CHECK_FAILED"
        }
        assert "background_update_check_failed" in caplog.text
        monkeypatch.setattr(app.state.updates, "check", lambda: {"status": "CURRENT"})
        response = client.post("/api/operations/update-check", json={})
        assert response.json() == {"status": "CURRENT"}
        assert not app.state.operations_update_error
