"""StatsForecast executorをAPIから独立Worker processまで通す。"""

import hashlib
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from test_run_api import snapshot_payload

pytest.importorskip("statsforecast")

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore


def test_api_to_statsforecast_worker_artifact_restore_end_to_end(tmp_path) -> None:
    data_path = tmp_path / "daily.csv"
    days = pd.date_range("2024-01-01", "2026-01-11")
    weekly = np.asarray([4.0, 8.0, 12.0, 7.0, 14.0, 3.0, 0.0])
    pd.DataFrame(
        {
            "unique_id": "A",
            "ds": days,
            "y": 30.0 + weekly[days.dayofweek] + np.arange(len(days)) * 0.01,
        }
    ).to_csv(data_path, index=False)
    raw = data_path.read_bytes()
    manifest = snapshot_payload(data_path.as_uri(), raw)
    database = tmp_path / "statsforecast.sqlite3"
    runs, catalog = SqliteRunStore(database), SqliteCatalogStore(database)
    api = TestClient(create_app(runs, catalog, "token", tmp_path))
    api.headers["Authorization"] = "Bearer token"
    snapshot_id = api.post("/api/snapshots", json=manifest).json()["id"]
    definition = {
        "snapshot_id": snapshot_id,
        "provider_id": "statsforecast-ets",
        "model_name": "auto_ets_weekly",
        "params": {"season_length": 7, "model": "ZZZ"},
        "interval_levels": [],
        "preprocessing_version": "statsforecast-causal-ffill-v1",
        "seed": 7,
        "resource_profile": "cpu-small",
    }
    experiment = api.post("/api/experiments", json=definition)
    assert experiment.status_code == 201, experiment.text
    created = api.post("/api/runs", json={"experiment_id": experiment.json()["id"]})
    run_id = created.json()["run_id"]
    command = [
        sys.executable,
        "-m",
        "forecast_provider.worker_process",
        "--sqlite",
        str(database),
        "--statsforecast-ets",
        "--artifact-root",
        str(tmp_path / "objects"),
        "--work-root",
        str(tmp_path / "work"),
        "--max-origins",
        "1",
        "--once",
    ]
    env = dict(os.environ, PYTHONUTF8="1")
    first = subprocess.run(command, capture_output=True, text=True, env=env, timeout=45)
    assert first.returncode == 0, first.stdout + first.stderr
    assert runs.get_run(run_id).status == "RUNNING"
    second = subprocess.run(command, capture_output=True, text=True, env=env, timeout=45)
    assert second.returncode == 0, second.stdout + second.stderr
    assert runs.get_run(run_id).status == "SUCCEEDED"
    origins = runs.rows("forecast_origins")
    assert origins[0]["model_artifact"] == origins[1]["model_artifact"]
    assert origins[0]["context_artifact"] != origins[1]["context_artifact"]
    # 2起点の対象は10日分+最終日1日分。POINTのみなので11行。
    assert len(runs.rows("forecast_values")) == 11
    assert hashlib.sha256(raw).hexdigest() == manifest["data_sha256"]
