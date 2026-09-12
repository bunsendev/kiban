"""TimesFM executorをAPIから共通Worker entry pointまで通す。"""

import hashlib

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from test_run_api import snapshot_payload

pytest.importorskip("timesfm")

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.providers.timesfm_checkpoint import (
    CHECKPOINT_SHA256,
    CHECKPOINT_SIZE,
    CheckpointRef,
)
from forecast_provider.providers.timesfm_runtime import MODEL_PARAMS
from forecast_provider.worker_process import main as worker_main


def test_api_to_timesfm_worker_artifact_restore_end_to_end(tmp_path, monkeypatch) -> None:
    data_path = tmp_path / "daily.csv"
    days = pd.date_range("2024-01-01", "2026-01-11")
    pd.DataFrame(
        {
            "unique_id": "A",
            "ds": days,
            "y": 30.0 + (days.dayofweek == 0) * 5 + np.arange(len(days)) * 0.01,
        }
    ).to_csv(data_path, index=False)
    raw = data_path.read_bytes()
    manifest = snapshot_payload(data_path.as_uri(), raw)
    database = tmp_path / "timesfm.sqlite3"
    runs, catalog = SqliteRunStore(database), SqliteCatalogStore(database)
    api = TestClient(create_app(runs, catalog, "token", tmp_path))
    api.headers["Authorization"] = "Bearer token"
    snapshot_id = api.post("/api/snapshots", json=manifest).json()["id"]
    definition = {
        "snapshot_id": snapshot_id,
        "provider_id": "timesfm-2p5",
        "model_name": "timesfm_2p5_200m_zero_shot",
        "params": dict(MODEL_PARAMS),
        "interval_levels": [],
        "preprocessing_version": "timesfm-causal-ffill-context512-v1",
        "seed": 7,
        "resource_profile": "cpu-timesfm",
    }
    experiment = api.post("/api/experiments", json=definition)
    assert experiment.status_code == 201, experiment.text
    created = api.post("/api/runs", json={"experiment_id": experiment.json()["id"]})
    run_id = created.json()["run_id"]
    checkpoint = CheckpointRef(
        tmp_path / "model.safetensors", CHECKPOINT_SHA256, CHECKPOINT_SIZE
    )
    monkeypatch.setattr(
        "forecast_provider.providers.timesfm_2p5.resolve_checkpoint", lambda: checkpoint
    )
    monkeypatch.setattr(
        "forecast_provider.providers.timesfm_2p5.forecast_timesfm",
        lambda ref, inputs, horizon: np.tile(
            np.arange(1, horizon + 1, dtype=float), (len(inputs), 1)
        ),
    )
    command = [
        "--sqlite",
        str(database),
        "--timesfm-2p5",
        "--artifact-root",
        str(tmp_path / "objects"),
        "--work-root",
        str(tmp_path / "work"),
        "--max-origins",
        "1",
        "--once",
    ]
    assert worker_main(command) == 0
    assert runs.get_run(run_id).status == "RUNNING"
    assert worker_main(command) == 0
    assert runs.get_run(run_id).status == "SUCCEEDED"
    origins = runs.rows("forecast_origins")
    assert origins[0]["model_artifact"] == origins[1]["model_artifact"]
    assert origins[0]["context_artifact"] != origins[1]["context_artifact"]
    assert len(runs.rows("forecast_values")) == 11
    assert hashlib.sha256(raw).hexdigest() == manifest["data_sha256"]
