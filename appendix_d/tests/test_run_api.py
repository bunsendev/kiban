"""Phase 1F catalog/run API契約。"""

import hashlib

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore


def snapshot_payload(data_uri="file:///tmp/data.csv", data=b"data"):
    return {
        "data_uri": data_uri,
        "data_sha256": hashlib.sha256(data).hexdigest(),
        "selection_version": "selection-v1",
        "unique_ids": ["A"],
        "train_start": "2024-01-01",
        "train_end": "2025-12-31",
        "test_start": "2026-01-01",
        "test_end": "2026-01-11",
        "origin_interval_days": 10,
        "max_horizon": 10,
        "primary_horizon_max": 10,
        "report_horizons": [1, 7, 10],
        "known_future_columns": [],
        "availability_mode": "ASSUMED",
    }


def experiment_payload(snapshot_id):
    return {
        "snapshot_id": snapshot_id,
        "provider_id": "builtin-baseline",
        "model_name": "moving_average_28",
        "params": {},
        "interval_levels": [0.8],
        "preprocessing_version": "daily-v1",
        "seed": 7,
        "resource_profile": "cpu-small",
    }


def client(tmp_path):
    path = tmp_path / "api.sqlite3"
    api = TestClient(create_app(SqliteRunStore(path), SqliteCatalogStore(path), "token"))
    api.headers["Authorization"] = "Bearer token"
    return api


def create_catalog(api):
    snapshot = api.post("/api/snapshots", json=snapshot_payload())
    assert snapshot.status_code == 201
    experiment = api.post("/api/experiments", json=experiment_payload(snapshot.json()["id"]))
    assert experiment.status_code == 201
    return snapshot.json()["id"], experiment.json()["id"]


def test_catalog_is_content_addressed_immutable_and_queryable(tmp_path):
    api = client(tmp_path)
    first, experiment = create_catalog(api)
    second = api.post("/api/snapshots", json=snapshot_payload())
    assert second.json()["id"] == first
    assert api.get(f"/api/snapshots/{first}").json()["format_version"] == 1
    assert api.get(f"/api/experiments/{experiment}").json()["snapshot_id"] == first


def test_run_accepts_only_saved_experiment_and_builds_plan_server_side(tmp_path):
    api = client(tmp_path)
    _, experiment = create_catalog(api)
    response = api.post("/api/runs", json={"experiment_id": experiment})
    assert response.status_code == 202
    state = api.get(f"/api/runs/{response.json()['run_id']}").json()
    assert state["origin_counts"] == {"QUEUED": 2}
    arbitrary = {"experiment_id": experiment, "origins": []}
    assert api.post("/api/runs", json=arbitrary).status_code == 422


def test_run_list_supports_status_filter_and_includes_provider_identity(tmp_path):
    api = client(tmp_path)
    _, experiment = create_catalog(api)
    created = api.post("/api/runs", json={"experiment_id": experiment}).json()

    response = api.get("/api/runs?limit=1&status=QUEUED")

    assert response.status_code == 200
    assert response.json() == [
        {
            "run_id": created["run_id"],
            "experiment_id": experiment,
            "status": "QUEUED",
            "cancellation_requested": False,
            "origin_counts": {"QUEUED": 2},
            "failure_count": 0,
            "provider_id": "builtin-baseline",
            "model_name": "moving_average_28",
            "resources": None,
        }
    ]
    assert api.get("/api/runs?status=UNKNOWN").status_code == 422
    assert api.get("/api/runs?limit=201").status_code == 422


def test_unknown_references_and_authentication(tmp_path):
    api = client(tmp_path)
    assert api.post("/api/experiments", json=experiment_payload("missing")).status_code == 404
    assert api.post("/api/runs", json={"experiment_id": "missing"}).status_code == 404
    bare = TestClient(
        create_app(
            SqliteRunStore(tmp_path / "bare.sqlite3"),
            SqliteCatalogStore(tmp_path / "bare.sqlite3"),
            "secret",
        )
    )
    assert bare.post("/api/snapshots", json=snapshot_payload()).status_code == 401


def test_invalid_dataset_and_experiment_contracts_are_422(tmp_path):
    api = client(tmp_path)
    invalid = snapshot_payload()
    invalid["test_start"] = "2026-01-02"
    assert api.post("/api/snapshots", json=invalid).status_code == 422
    snapshot, _ = create_catalog(api)
    invalid_experiment = experiment_payload(snapshot)
    invalid_experiment["preprocessing_version"] = ""
    assert api.post("/api/experiments", json=invalid_experiment).status_code == 422
    invalid_experiment = experiment_payload(snapshot)
    invalid_experiment["model_name"] = "unknown"
    assert api.post("/api/experiments", json=invalid_experiment).status_code == 422


def test_dynamic_future_feature_requires_versioned_source(tmp_path):
    api = client(tmp_path)
    invalid = snapshot_payload()
    invalid["known_future_columns"] = ["promotion"]
    response = api.post("/api/snapshots", json=invalid)
    assert response.status_code == 422

    valid = {
        **invalid,
        "feature_versions_uri": "file:///tmp/features.csv",
        "feature_versions_sha256": hashlib.sha256(b"features").hexdigest(),
    }
    assert api.post("/api/snapshots", json=valid).status_code == 201
