"""Phase 3I: 複数OSSモデル比較キャンペーンの統合契約。"""

import hashlib
import sqlite3

import pandas as pd
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.comparison_campaign import SqliteComparisonCampaignStore
from forecast_provider.evaluation_registry import SqliteEvaluationRegistryStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.provider_conformance import SqliteConformanceJobStore


def _fixture(tmp_path):
    database = tmp_path / "phase3i.sqlite3"
    runs = SqliteRunStore(database)
    catalog = SqliteCatalogStore(database)
    evaluations = SqliteEvaluationRegistryStore(database)
    jobs = SqliteConformanceJobStore(database)
    campaigns = SqliteComparisonCampaignStore(database)
    api = TestClient(
        create_app(
            runs,
            catalog,
            "token",
            tmp_path,
            evaluation_registry=evaluations,
            conformance_jobs=jobs,
            comparison_campaigns=campaigns,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    path = tmp_path / "daily.csv"
    pd.DataFrame(
        {"unique_id": ["A"], "ds": ["2025-01-01"], "y": [1.0]}
    ).to_csv(path, index=False)
    response = api.post(
        "/api/snapshots",
        json={
            "data_uri": path.as_uri(),
            "data_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "selection_version": "selection-v1",
            "unique_ids": ["A"],
            "train_start": "2024-01-01",
            "train_end": "2025-02-23",
            "test_start": "2025-02-24",
            "test_end": "2025-03-10",
            "origin_interval_days": 15,
            "max_horizon": 15,
            "primary_horizon_max": 15,
            "report_horizons": [1, 7, 15],
            "known_future_columns": [],
            "availability_mode": "ASSUMED",
        },
    )
    assert response.status_code == 201, response.text
    return api, response.json()["id"], database


def _request(snapshot_id, key="campaign-request-001"):
    return {
        "request_key": key,
        "snapshot_id": snapshot_id,
        "models": [
            {"provider_id": "builtin-baseline", "model_id": "seasonal_naive_7"},
            {"provider_id": "builtin-baseline", "model_id": "moving_average_28"},
        ],
        "purpose": "OSSモデル選定",
    }


def test_campaign_registers_experiments_conformance_jobs_and_runs_once(tmp_path):
    api, snapshot_id, database = _fixture(tmp_path)

    first = api.post("/api/comparison-campaigns", json=_request(snapshot_id))
    second = api.post("/api/comparison-campaigns", json=_request(snapshot_id))

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["campaign_id"] == second.json()["campaign_id"]
    assert first.json()["status"] == "RUNNING"
    assert len(first.json()["entries"]) == 2
    assert {item["run_status"] for item in first.json()["entries"]} == {"QUEUED"}
    assert {item["conformance_status"] for item in first.json()["entries"]} == {"QUEUED"}
    assert {item["run_id"] for item in first.json()["entries"]} == {
        item["run_id"] for item in second.json()["entries"]
    }
    assert len(api.get("/api/runs").json()) == 2
    assert len(api.get("/api/provider-conformance-jobs").json()) == 2
    listing = api.get("/api/comparison-campaigns")
    assert listing.status_code == 200
    assert listing.json()[0]["purpose"] == "OSSモデル選定"

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE forecast_runs SET status='SUCCEEDED'")
        connection.execute("UPDATE provider_conformance_jobs SET status='SUCCEEDED'")
    detail = api.get(f"/api/comparison-campaigns/{first.json()['campaign_id']}")
    assert detail.json()["status"] == "COMPLETED"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE forecast_runs SET status='FAILED' WHERE run_id=?",
            (first.json()["entries"][0]["run_id"],),
        )
    detail = api.get(f"/api/comparison-campaigns/{first.json()['campaign_id']}")
    assert detail.json()["status"] == "NEEDS_ATTENTION"


def test_campaign_validates_selection_request_key_and_permissions(tmp_path):
    api, snapshot_id, _database = _fixture(tmp_path)
    payload = _request(snapshot_id)
    created = api.post("/api/comparison-campaigns", json=payload)
    assert created.status_code == 202

    changed = {**payload, "purpose": "別の目的"}
    assert api.post("/api/comparison-campaigns", json=changed).status_code == 422
    duplicate = {
        **payload,
        "request_key": "campaign-request-002",
        "models": payload["models"][:1] * 2,
    }
    assert api.post("/api/comparison-campaigns", json=duplicate).status_code == 422
    invalid_model = _request(snapshot_id, "campaign-request-004")
    invalid_model["models"][1]["model_id"] = "unknown"
    assert api.post("/api/comparison-campaigns", json=invalid_model).status_code == 422
    assert len(api.get("/api/comparison-campaigns").json()) == 1
    missing = _request("missing", "campaign-request-003")
    assert api.post("/api/comparison-campaigns", json=missing).status_code == 404
    assert api.get("/api/comparison-campaigns/missing").status_code == 404

    authorization = api.headers.pop("Authorization")
    try:
        assert api.get("/api/comparison-campaigns").status_code == 401
        assert api.post("/api/comparison-campaigns", json=payload).status_code == 401
    finally:
        api.headers["Authorization"] = authorization


def test_analysis_ui_exposes_batch_campaign_flow(tmp_path):
    api, _, _database = _fixture(tmp_path)

    page = api.get("/ui/analysis")
    client = api.get("/ui/assets/analysis_api.js")
    app = api.get("/ui/assets/analysis_app.js")
    renderer = api.get("/ui/assets/analysis_render.js")

    assert "比較セットをまとめて開始" in page.text
    assert 'request("/api/comparison-campaigns")' in client.text
    assert "createCampaign" in app.text
    assert "renderCampaigns" in renderer.text
