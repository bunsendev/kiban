"""Phase 3L: 複数条件の一括登録と横断比較表示。"""

import hashlib
import json
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
    database = tmp_path / "phase3l.sqlite3"
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            tmp_path,
            evaluation_registry=SqliteEvaluationRegistryStore(database),
            conformance_jobs=SqliteConformanceJobStore(database),
            comparison_campaigns=SqliteComparisonCampaignStore(database),
        )
    )
    api.headers["Authorization"] = "Bearer token"
    return api, _second_snapshot(api, tmp_path, version="selection-v1"), database


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


def _second_snapshot(api, tmp_path, version="selection-v2") -> str:
    suffix = version.rsplit("-", 1)[-1]
    horizon = 15 if version == "selection-v1" else 7
    path = tmp_path / f"daily-{suffix}.csv"
    pd.DataFrame({"unique_id": [suffix], "ds": ["2025-01-01"], "y": [2.0]}).to_csv(
        path, index=False
    )
    response = api.post(
        "/api/snapshots",
        json={
            "data_uri": path.as_uri(),
            "data_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "selection_version": version,
            "unique_ids": [suffix],
            "train_start": "2024-01-01",
            "train_end": "2025-01-24",
            "test_start": "2025-01-25",
            "test_end": "2025-02-08",
            "origin_interval_days": horizon,
            "max_horizon": horizon,
            "primary_horizon_max": horizon,
            "report_horizons": [1, 7] if horizon == 7 else [1, 7, 15],
            "known_future_columns": [],
            "availability_mode": "ASSUMED",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _batch(snapshot_ids: list[str]) -> dict:
    request = _request(snapshot_ids[0], "retest-matrix-001")
    request.pop("snapshot_id")
    return {**request, "snapshot_ids": snapshot_ids}


def test_batch_registers_each_snapshot_once_and_validates_scope(tmp_path):
    api, first_snapshot, database = _fixture(tmp_path)
    second_snapshot = _second_snapshot(api, tmp_path)
    payload = _batch([first_snapshot, second_snapshot])

    first = api.post("/api/comparison-campaign-batches", json=payload)
    second = api.post("/api/comparison-campaign-batches", json=payload)

    assert first.status_code == second.status_code == 202
    assert first.json()["campaign_count"] == 2
    assert [item["campaign_id"] for item in first.json()["campaigns"]] == [
        item["campaign_id"] for item in second.json()["campaigns"]
    ]
    assert {item["snapshot_id"] for item in first.json()["campaigns"]} == {
        first_snapshot,
        second_snapshot,
    }
    assert len(api.get("/api/comparison-campaigns").json()) == 2
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM forecast_runs").fetchone()[0] == 4

    reordered = {**payload, "snapshot_ids": list(reversed(payload["snapshot_ids"]))}
    assert api.post("/api/comparison-campaign-batches", json=reordered).status_code == 422
    duplicate = {
        **payload,
        "request_key": "retest-matrix-002",
        "snapshot_ids": [first_snapshot] * 2,
    }
    assert api.post("/api/comparison-campaign-batches", json=duplicate).status_code == 422
    missing = {
        **payload,
        "request_key": "retest-matrix-003",
        "snapshot_ids": [first_snapshot, "missing"],
    }
    assert api.post("/api/comparison-campaign-batches", json=missing).status_code == 404

    authorization = api.headers.pop("Authorization")
    try:
        assert api.post("/api/comparison-campaign-batches", json=payload).status_code == 401
        assert api.get("/api/comparison-campaign-results").status_code == 401
    finally:
        api.headers["Authorization"] = authorization


def test_result_matrix_uses_only_completed_official_metrics(tmp_path):
    api, first_snapshot, database = _fixture(tmp_path)
    second_snapshot = _second_snapshot(api, tmp_path)
    created = api.post(
        "/api/comparison-campaign-batches", json=_batch([first_snapshot, second_snapshot])
    ).json()
    with sqlite3.connect(database) as connection:
        for campaign_index, campaign in enumerate(created["campaigns"], 1):
            comparison_id = f"comparison-phase3l-{campaign_index}"
            scores = {}
            for model_index, entry in enumerate(campaign["entries"], 1):
                scores[entry["run_id"]] = {
                    "official_eligible": True,
                    "official_common_metrics": {
                        "wape_pct": float(campaign_index * 10 + model_index),
                        "mae": float(model_index),
                        "rmse": float(model_index + 1),
                        "bias_rate_pct": float(model_index - 2),
                    },
                    "run_success_rate": 1.0,
                }
            result = {"scores": scores}
            connection.execute(
                "INSERT INTO comparison_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    comparison_id,
                    1,
                    f"fingerprint-phase3l-{campaign_index}",
                    "{}",
                    json.dumps(result),
                    "set",
                    "official",
                    "truth",
                    "scope",
                    "primary",
                    None,
                    1,
                    1,
                    "2026-09-19T00:00:00+00:00",
                ),
            )
            connection.execute(
                "UPDATE comparison_campaign_finalizations "
                "SET status='SUCCEEDED',comparison_id=? WHERE campaign_id=?",
                (comparison_id, campaign["campaign_id"]),
            )

    response = api.get("/api/comparison-campaign-results?limit=20")

    assert response.status_code == 200, response.text
    tests = response.json()["tests"]
    assert len(tests) == 2
    assert {item["selection_version"] for item in tests} == {"selection-v1", "selection-v2"}
    assert {item["primary_horizon_max"] for item in tests} == {7, 15}
    for test in tests:
        ranked = sorted(test["models"], key=lambda item: item["wape_pct"])
        assert [item["rank"] for item in ranked] == [1, 2]
        assert all(item["success_rate_pct"] == 100 for item in test["models"])

    assert api.get("/api/comparison-campaign-results?limit=0").status_code == 422
