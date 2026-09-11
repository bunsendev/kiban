"""Phase 1S: 月次拡大学習とmodel artifactの月内再利用。"""

import hashlib
from dataclasses import replace
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from test_builtin_baseline import make_context, make_dataset
from test_job_resume import make_store, point
from test_run_api import snapshot_payload

from forecast_provider import ProviderConfig
from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.errors import ContractViolationError
from forecast_provider.executors import BuiltinBaselineExecutor
from forecast_provider.jobs import OriginOutput, SqliteRunStore
from forecast_provider.runner import run_monthly_provider
from forecast_provider.training import training_cutoff, training_cutoffs, training_dataset
from forecast_provider.worker_process import work_once


def monthly_dataset():
    return replace(make_dataset(("A",)), test_end=date(2026, 3, 21))


def test_monthly_cutoffs_derive_from_actual_origin_schedule():
    dataset = monthly_dataset()

    assert training_cutoffs(dataset, "MONTHLY_EXPANDING") == (
        date(2025, 12, 31),
        date(2026, 1, 10),
        date(2026, 2, 9),
        date(2026, 3, 1),
    )
    assert training_cutoff(dataset, date(2026, 1, 30), "MONTHLY_EXPANDING") == date(
        2026, 1, 10
    )
    expanded = training_dataset(dataset, date(2026, 2, 9))
    assert expanded.train_start == dataset.train_start
    assert expanded.train_end == date(2026, 2, 9)
    assert expanded.test_start == date(2026, 2, 10)
    with pytest.raises(ContractViolationError):
        training_cutoff(dataset, date(2026, 1, 1), "MONTHLY_EXPANDING")


def test_monthly_runner_refits_once_per_scheduled_month():
    dataset = monthly_dataset()
    data = pd.DataFrame(
        {
            "unique_id": "A",
            "ds": pd.date_range(dataset.train_start, dataset.test_end),
            "y": 10.0,
        }
    )
    config = ProviderConfig(
        "builtin-baseline",
        "moving_average_28",
        preprocessing_version="daily-nan-preserving-v1",
    )

    result = run_monthly_provider(
        data, dataset, config, make_context(), availability_mode="ASSUMED"
    )

    assert result["status"] == "SUCCESS"
    assert result["fit_calls"] == 4
    assert result["refit_cutoffs"] == tuple(
        value.isoformat() for value in training_cutoffs(dataset, "MONTHLY_EXPANDING")
    )


def test_run_store_finds_artifact_only_inside_requested_month(tmp_path):
    store = make_store(tmp_path, days=(1, 2))
    store.start_or_resume("run-1", "fingerprint-1")
    first = store.claim_next_origin("run-1", "worker", 60)
    store.complete_origin(first, OriginOutput((point(1),), "model-january", "context"))

    assert (
        store.get_model_artifact("run-1", date(2026, 1, 1), date(2026, 2, 1))
        == "model-january"
    )
    assert store.get_model_artifact("run-1", date(2026, 2, 1), date(2026, 3, 1)) is None
    with pytest.raises(ValueError):
        store.get_model_artifact("run-1", date(2026, 1, 1), None)


def test_worker_persists_one_model_artifact_per_scheduled_month(tmp_path):
    data_path = tmp_path / "daily.csv"
    days = pd.date_range("2024-01-01", "2026-03-21")
    pd.DataFrame({"unique_id": "A", "ds": days, "y": 10.0}).to_csv(
        data_path, index=False
    )
    raw = data_path.read_bytes()
    manifest = {
        **snapshot_payload(data_path.as_uri(), raw),
        "test_end": "2026-03-21",
    }
    database = tmp_path / "monthly-worker.sqlite3"
    runs = SqliteRunStore(database)
    catalog = SqliteCatalogStore(database)
    api = TestClient(create_app(runs, catalog, "token", tmp_path))
    api.headers["Authorization"] = "Bearer token"
    snapshot_id = api.post("/api/snapshots", json=manifest).json()["id"]
    experiment = api.post(
        "/api/experiments",
        json={
            "snapshot_id": snapshot_id,
            "provider_id": "builtin-baseline",
            "model_name": "moving_average_28",
            "params": {},
            "interval_levels": [],
            "preprocessing_version": "daily-nan-preserving-v1",
            "seed": 7,
            "resource_profile": "cpu-small",
            "training_policy": "MONTHLY_EXPANDING",
        },
    )
    run_id = api.post(
        "/api/runs", json={"experiment_id": experiment.json()["id"]}
    ).json()["run_id"]
    executor = BuiltinBaselineExecutor(runs, catalog, tmp_path / "objects", tmp_path / "work")

    assert work_once(runs, executor, "monthly-worker") == 1
    assert runs.get_run(run_id).status == "SUCCEEDED"

    origins = runs.rows("forecast_origins")
    models_by_month = {}
    for origin in origins:
        models_by_month.setdefault(origin["origin_date"][:7], set()).add(
            origin["model_artifact"]
        )
    assert len(models_by_month) == 4
    assert all(len(artifacts) == 1 for artifacts in models_by_month.values())
    assert len({next(iter(value)) for value in models_by_month.values()}) == 4
    assert hashlib.sha256(raw).hexdigest() == manifest["data_sha256"]
