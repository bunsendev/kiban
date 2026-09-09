"""APIからrun作成し、別Workerプロセスでartifact復元して完了する。"""

import hashlib
import os
import subprocess
import sys

import pandas as pd
from fastapi.testclient import TestClient
from test_run_api import experiment_payload, snapshot_payload

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore


def test_api_to_baseline_worker_artifact_restore_end_to_end(tmp_path):
    data_path = tmp_path / "daily.csv"
    days = pd.date_range("2024-01-01", "2026-01-11")
    pd.DataFrame(
        {"unique_id": "A", "ds": days, "y": [float(i % 17) for i in range(len(days))]}
    ).to_csv(data_path, index=False)
    raw = data_path.read_bytes()
    manifest = snapshot_payload(data_path.as_uri(), raw)
    database = tmp_path / "phase1f.sqlite3"
    runs = SqliteRunStore(database)
    catalog = SqliteCatalogStore(database)
    api = TestClient(create_app(runs, catalog, "token", tmp_path))
    api.headers["Authorization"] = "Bearer token"
    snapshot_id = api.post("/api/snapshots", json=manifest).json()["id"]
    experiment_id = api.post("/api/experiments", json=experiment_payload(snapshot_id)).json()["id"]
    created = api.post("/api/runs", json={"experiment_id": experiment_id})
    assert created.status_code == 202
    run_id = created.json()["run_id"]

    command = [
        sys.executable,
        "-m",
        "forecast_provider.worker_process",
        "--sqlite",
        str(database),
        "--builtin-baseline",
        "--artifact-root",
        str(tmp_path / "objects"),
        "--work-root",
        str(tmp_path / "work"),
        "--max-origins",
        "1",
        "--once",
    ]
    env = dict(os.environ, PYTHONUTF8="1")
    first = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
    assert first.returncode == 0, first.stdout + first.stderr
    assert runs.get_run(run_id).status == "RUNNING"
    first_origin = runs.rows("forecast_origins")[0]
    assert first_origin["model_artifact"] and first_origin["context_artifact"]

    second = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
    assert second.returncode == 0, second.stdout + second.stderr
    assert runs.get_run(run_id).status == "SUCCEEDED"
    origins = runs.rows("forecast_origins")
    assert origins[0]["model_artifact"] == origins[1]["model_artifact"]
    assert origins[0]["context_artifact"] != origins[1]["context_artifact"]
    assert len(runs.rows("forecast_values")) == 44
    assert hashlib.sha256(raw).hexdigest() == manifest["data_sha256"]
    results = api.get(f"/api/runs/{run_id}/results")
    assert results.status_code == 200
    assert len(results.json()["values"]) == 44
    assert results.json()["failures"] == []
    assert all(row["model_artifact"] for row in results.json()["origins"])
    assert all(isinstance(row["model_artifact"], dict) for row in results.json()["origins"])
    point = next(row for row in results.json()["values"] if row["forecast_kind"] == "POINT")
    assert point["quantile"] is None and isinstance(point["yhat"], float | int)
    assert all(row["cutoff_at"].endswith("+09:00") for row in results.json()["origins"])


def test_tampered_snapshot_fails_without_prediction_output(tmp_path):
    data_path = tmp_path / "daily.csv"
    days = pd.date_range("2024-01-01", "2026-01-11")
    pd.DataFrame({"unique_id": "A", "ds": days, "y": 1.0}).to_csv(data_path, index=False)
    database = tmp_path / "tampered.sqlite3"
    runs, catalog = SqliteRunStore(database), SqliteCatalogStore(database)
    api = TestClient(create_app(runs, catalog, "token", tmp_path))
    api.headers["Authorization"] = "Bearer token"
    raw = data_path.read_bytes()
    snapshot = api.post("/api/snapshots", json=snapshot_payload(data_path.as_uri(), raw)).json()[
        "id"
    ]
    experiment = api.post("/api/experiments", json=experiment_payload(snapshot)).json()["id"]
    run_id = api.post("/api/runs", json={"experiment_id": experiment}).json()["run_id"]
    data_path.write_text("tampered", encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "forecast_provider.worker_process",
        "--sqlite",
        str(database),
        "--builtin-baseline",
        "--artifact-root",
        str(tmp_path / "objects"),
        "--work-root",
        str(tmp_path / "work"),
        "--once",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert runs.get_run(run_id).status == "FAILED"
    assert runs.rows("forecast_values") == []
    assert len(runs.rows("forecast_failures")) == 2
