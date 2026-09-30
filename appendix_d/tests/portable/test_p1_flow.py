"""P1 acceptance tests: persistence, deterministic baseline, recovery and local boundary."""

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.api.store import RunStore
from portable.launcher.main import available_ports, request_json, start_server, stop_server
from portable.runtime.paths import DataPaths
from portable.runtime.windows import AlreadyRunning, ChildJob, SingleInstance


def synthetic_csv() -> bytes:
    rows = ["ds,unique_id,y"]
    for uid, offset in [("SYNTHETIC-001", 0), ("SYNTHETIC-002", 10)]:
        for day in range(28):
            date = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)).date()
            rows.append(f"{date},{uid},{day % 7 + offset}")
    return ("\n".join(rows) + "\n").encode()


def test_end_to_end_and_restart(tmp_path: Path):
    data = (
        Path(__file__).resolve().parents[2] / "portable" / "sample" / "synthetic_shipments.csv"
    ).read_bytes()
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert client.get("/api/sample.csv").content == data
    first = client.post("/api/runs", content=data, headers={"Content-Type": "text/csv"})
    assert first.status_code == 201, first.text
    result = first.json()
    assert result["status"] == "SUCCESS"
    assert result["input_sha256"] == hashlib.sha256(data).hexdigest()
    assert len(result["predictions"]) == 14
    assert (tmp_path / "Results" / f"{result['run_id']}.json").is_file()
    assert client.get(f"/api/runs/{result['run_id']}/download").status_code == 200

    restarted = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    history = restarted.get("/api/runs").json()
    assert history[0]["run_id"] == result["run_id"]
    again = restarted.post("/api/runs", content=data, headers={"Content-Type": "text/csv"})
    assert again.status_code == 201, again.text
    assert again.json()["input_sha256"] == result["input_sha256"]
    assert again.json()["result_sha256"] == result["result_sha256"]
    assert again.json()["predictions"] == result["predictions"]


def test_interrupted_run_is_not_success(tmp_path: Path):
    store = RunStore(tmp_path / "runs.sqlite3")
    store.start("interrupted", "hash", "v1", "baseline")
    reopened = RunStore(tmp_path / "runs.sqlite3")
    assert reopened.get("interrupted")["status"] == "INTERRUPTED"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"junk\n",
        b"ds,unique_id,y\n2026-01-01,A,-1\n",
        b"ds,unique_id,y\n2026-01-01,A,1\n2026-01-01,A,2\n",
    ],
)
def test_invalid_csv_is_rejected_without_success(tmp_path: Path, data: bytes):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    response = client.post("/api/runs", content=data, headers={"Content-Type": "text/csv"})
    assert response.status_code == 422
    assert client.get("/api/runs").json()[0]["status"] == "FAILED"


def test_local_boundary_and_result_integrity(tmp_path: Path):
    client = TestClient(create_app(tmp_path, control_token="secret"), base_url="http://127.0.0.1")
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
    assert (
        client.post(
            "/api/runs",
            content=synthetic_csv(),
            headers={"Content-Type": "text/csv", "Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert client.post("/api/control/drain").status_code == 403
    result = client.post(
        "/api/runs", content=synthetic_csv(), headers={"Content-Type": "text/csv"}
    ).json()
    path = tmp_path / "Results" / f"{result['run_id']}.json"
    path.write_text(json.dumps([{"tampered": True}]), encoding="utf-8")
    assert client.get(f"/api/runs/{result['run_id']}").status_code == 500
    assert client.post("/api/control/drain", headers={"X-Portable-Control": "secret"}).json() == {
        "active": 0
    }
    assert (
        client.post(
            "/api/runs", content=synthetic_csv(), headers={"Content-Type": "text/csv"}
        ).status_code
        == 503
    )


def test_port_collision_selects_next_port():
    import socket

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 48150))
        assert next(available_ports()) != 48150


def test_mutex_prevents_double_start_and_recovers(tmp_path: Path):
    with SingleInstance(tmp_path):
        with pytest.raises(AlreadyRunning):
            with SingleInstance(tmp_path):
                pass
    with SingleInstance(tmp_path):
        pass


def test_unwritable_data_root_fails_early(tmp_path: Path):
    (tmp_path / "State").write_text("blocks a directory", encoding="utf-8")
    with pytest.raises(OSError):
        DataPaths(tmp_path).ensure()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object only")
def test_supervised_source_server_starts_and_stops(tmp_path: Path):
    paths = DataPaths(tmp_path)
    paths.ensure()
    job = ChildJob()
    token = secrets.token_urlsafe(24)
    try:
        child, port = start_server(paths, job, token)
        assert request_json(port, "/ready")["ready"]
        assert child.poll() is None
        stop_server(child, port, token)
        assert child.poll() is not None
    finally:
        job.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object only")
def test_launcher_crash_kills_api_and_releases_mutex(tmp_path: Path):
    import ctypes

    helper = Path(__file__).with_name("crash_helper.py")
    process = subprocess.Popen(
        [sys.executable, str(helper), str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        marker = tmp_path / "child.pid"
        for _ in range(150):
            if marker.is_file():
                break
            if process.poll() is not None:
                raise AssertionError("helper exited before API was ready")
            time.sleep(0.1)
        else:
            raise AssertionError("API never became ready")
        pid = int(marker.read_text(encoding="ascii").split(",")[0])
        process.kill()
        process.wait(timeout=5)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 10_000) == 0
            finally:
                kernel.CloseHandle(handle)
        with SingleInstance(tmp_path):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
