"""Phase 3H: UI起点Provider適合試験jobの統合契約。"""

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.evaluation_registry import SqliteEvaluationRegistryStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.provider_conformance import SqliteConformanceJobStore
from forecast_provider.provider_conformance_worker import work_once


def _fixture(tmp_path):
    database = tmp_path / "phase3h.sqlite3"
    runs = SqliteRunStore(database)
    catalog = SqliteCatalogStore(database)
    evaluations = SqliteEvaluationRegistryStore(database)
    jobs = SqliteConformanceJobStore(database)
    api = TestClient(
        create_app(
            runs,
            catalog,
            "token",
            tmp_path,
            evaluation_registry=evaluations,
            conformance_jobs=jobs,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    path = tmp_path / "daily.csv"
    pd.DataFrame(
        {"unique_id": ["A"], "ds": ["2025-01-01"], "y": [1.0]}
    ).to_csv(path, index=False)
    snapshot = api.post(
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
    assert snapshot.status_code == 201, snapshot.text
    experiment = api.post(
        "/api/experiments",
        json={
            "snapshot_id": snapshot.json()["id"],
            "provider_id": "builtin-baseline",
            "model_name": "moving_average_28",
            "params": {},
            "interval_levels": [],
            "preprocessing_version": "daily-v1",
            "seed": 7,
            "resource_profile": "cpu-small",
            "training_policy": "FIXED",
        },
    )
    assert experiment.status_code == 201, experiment.text
    return api, catalog, evaluations, jobs, experiment.json()["id"]


def test_job_executes_fixed_checks_and_registers_tamper_evident_record(tmp_path):
    api, catalog, evaluations, jobs, experiment_id = _fixture(tmp_path)

    created = api.post(
        "/api/provider-conformance-jobs", json={"experiment_id": experiment_id}
    )

    assert created.status_code == 202
    job_id = created.json()["job_id"]
    assert created.json()["status"] == "QUEUED"
    assert work_once(
        jobs,
        catalog,
        evaluations,
        "builtin-baseline",
        tmp_path / "evidence",
    ) == 1
    job = api.get(f"/api/provider-conformance-jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["status"] == "SUCCEEDED"
    assert job.json()["error_message"] is None

    record = api.get(
        f"/api/provider-conformance-tests/{job.json()['conformance_id']}"
    ).json()
    assert record["status"] == "PASSED"
    assert record["fixed_ranking_eligible"] is True
    assert {item["code"] for item in record["checks"]} == {
        "TRAIN_BOUNDARY",
        "PARAMETER_IMMUTABILITY",
        "CONTEXT_REFRESH",
        "FUTURE_NON_REFERENCE",
        "OUTPUT_COMPLETENESS",
        "REPRODUCIBILITY",
        "FAILURE_NOTIFICATION",
    }
    assert all(item["status"] == "PASSED" for item in record["checks"])
    evidence_path = Path(urlparse(record["evidence_uri"]).path.lstrip("/"))
    if not evidence_path.exists():  # Windows file URI (/C:/...) をPathへ戻す。
        evidence_path = Path(urlparse(record["evidence_uri"]).path[1:])
    content = evidence_path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == record["evidence_sha256"]
    assert json.loads(content)["experiment_id"] == experiment_id


def test_job_api_deduplicates_active_job_and_filters_by_provider(tmp_path):
    api, catalog, evaluations, jobs, experiment_id = _fixture(tmp_path)

    first = api.post(
        "/api/provider-conformance-jobs", json={"experiment_id": experiment_id}
    )
    second = api.post(
        "/api/provider-conformance-jobs", json={"experiment_id": experiment_id}
    )

    assert first.json()["job_id"] == second.json()["job_id"]
    assert work_once(jobs, catalog, evaluations, "statsforecast-ets", tmp_path) == 0
    listing = api.get(
        "/api/provider-conformance-jobs", params={"experiment_id": experiment_id}
    )
    assert listing.status_code == 200
    assert [item["job_id"] for item in listing.json()] == [first.json()["job_id"]]
    assert api.post(
        "/api/provider-conformance-jobs", json={"experiment_id": "missing"}
    ).status_code == 404

    authorization = api.headers.pop("Authorization")
    try:
        assert api.get("/api/provider-conformance-jobs").status_code == 401
        assert api.post(
            "/api/provider-conformance-jobs", json={"experiment_id": experiment_id}
        ).status_code == 401
    finally:
        api.headers["Authorization"] = authorization


def test_worker_records_safe_failure_and_failed_job_can_be_retried(tmp_path):
    api, catalog, evaluations, jobs, experiment_id = _fixture(tmp_path)
    created = api.post(
        "/api/provider-conformance-jobs", json={"experiment_id": experiment_id}
    ).json()
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("file", encoding="utf-8")

    assert work_once(
        jobs, catalog, evaluations, "builtin-baseline", invalid_root
    ) == 1
    failed = api.get(
        f"/api/provider-conformance-jobs/{created['job_id']}"
    ).json()
    assert failed["status"] == "FAILED"
    assert failed["error_code"]
    assert failed["error_message"]

    retried = api.post(
        "/api/provider-conformance-jobs", json={"experiment_id": experiment_id}
    )
    assert retried.status_code == 202
    assert retried.json()["job_id"] != created["job_id"]
    assert retried.json()["status"] == "QUEUED"


def test_analysis_ui_exposes_conformance_job_flow(tmp_path):
    api, _, _, _, _ = _fixture(tmp_path)

    page = api.get("/ui/analysis")
    client = api.get("/ui/assets/analysis_api.js")
    app = api.get("/ui/assets/analysis_app.js")
    renderer = api.get("/ui/assets/analysis_render.js")

    assert "適合試験を行う" in page.text
    assert 'request("/api/provider-conformance-jobs")' in client.text
    assert "createConformanceJob" in app.text
    assert "適合試験を再実行" in renderer.text
    assert "固定7項目に合格" in renderer.text
