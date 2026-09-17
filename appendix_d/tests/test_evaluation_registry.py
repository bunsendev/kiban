"""Provider適合記録と保存済みrun比較の統合契約。"""

from __future__ import annotations

import hashlib
import sqlite3
from decimal import Decimal

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.catalog.domain import dataset_from_snapshot
from forecast_provider.evaluation import build_plan
from forecast_provider.evaluation_registry import REQUIRED_CHECKS, SqliteEvaluationRegistryStore
from forecast_provider.jobs import ForecastValue, OriginOutput, SqliteRunStore
from forecast_provider.registry import registry
from forecast_provider.resource_cost import ResourceMetric, ResourceUsage, SqliteResourceCostStore


def _fixture(tmp_path):
    data_path = tmp_path / "daily.csv"
    days = pd.date_range("2024-01-01", "2026-01-11")
    pd.DataFrame(
        {
            "unique_id": "A",
            "canonical_product_id": "P1",
            "center_id": "C1",
            "ds": days,
            "y": 10.0,
        }
    ).to_csv(data_path, index=False)
    database = tmp_path / "evaluation.sqlite3"
    runs = SqliteRunStore(database)
    catalog = SqliteCatalogStore(database)
    evaluations = SqliteEvaluationRegistryStore(database)
    resources = SqliteResourceCostStore(database)
    api = TestClient(
        create_app(
            runs,
            catalog,
            "token",
            tmp_path,
            evaluation_registry=evaluations,
            resource_cost=resources,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    raw = data_path.read_bytes()
    snapshot_payload = {
        "data_uri": data_path.as_uri(),
        "data_sha256": hashlib.sha256(raw).hexdigest(),
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
    snapshot_id = api.post("/api/snapshots", json=snapshot_payload).json()["id"]
    return api, runs, catalog, data_path, snapshot_id


def _experiment(
    api, snapshot_id: str, model: str, training_policy: str = "FIXED"
) -> tuple[str, dict]:
    definition = {
        "snapshot_id": snapshot_id,
        "provider_id": "builtin-baseline",
        "model_name": model,
        "params": {},
        "interval_levels": [],
        "preprocessing_version": "daily-v1",
        "seed": 7,
        "resource_profile": "cpu-small",
        "training_policy": training_policy,
    }
    response = api.post("/api/experiments", json=definition)
    assert response.status_code == 201, response.text
    return response.json()["id"], definition


def _statsforecast_experiment(api, snapshot_id: str) -> tuple[str, dict]:
    pytest.importorskip("statsforecast")
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
    response = api.post("/api/experiments", json=definition)
    assert response.status_code == 201, response.text
    return response.json()["id"], definition


def _completed_run(api, runs, catalog, experiment_id: str, yhat: int) -> str:
    response = api.post("/api/runs", json={"experiment_id": experiment_id})
    run_id = response.json()["run_id"]
    run = runs.get_run(run_id)
    snapshot = catalog.get_snapshot(catalog.get_experiment(experiment_id).snapshot_id)
    plan = build_plan(dataset_from_snapshot(snapshot))
    runs.start_or_resume(run_id, run.condition_fingerprint)
    while (lease := runs.claim_next_origin(run_id, "test-worker", 60)) is not None:
        targets = plan[plan.origin_date.eq(pd.Timestamp(lease.origin.origin_date))]
        values = tuple(
            ForecastValue(
                row.unique_id,
                row.origin_date.date(),
                row.target_date.date(),
                int(row.horizon),
                "POINT",
                None,
                Decimal(yhat),
                Decimal(yhat),
            )
            for row in targets.itertuples(index=False)
        )
        runs.complete_origin(lease, OriginOutput(values))
    assert runs.finish_run(run_id) == "SUCCEEDED"
    return run_id


def _conformance(api, definition: dict, *, failed: bool = False) -> str:
    metadata = registry.create(definition["provider_id"]).metadata()
    payload = {
        "provider_id": metadata.provider_id,
        "provider_version": metadata.provider_version,
        "model_id": definition["model_name"],
        "library_name": metadata.library_name,
        "library_version": metadata.library_version,
        "test_suite_version": "provider-contract-v1",
        "adapter_config": {
            "params": definition["params"],
            "interval_levels": definition["interval_levels"],
            "preprocessing_version": definition["preprocessing_version"],
        },
        "environment": {
            "python_version": "3.13.7",
            "platform": "test",
            "dependencies": {metadata.library_name: metadata.library_version},
            "container_digest": None,
        },
        "checks": [
            {
                "code": code,
                "status": "FAILED" if failed and code == "REPRODUCIBILITY" else "PASSED",
                "evidence": f"test:{code}",
            }
            for code in sorted(REQUIRED_CHECKS)
        ],
        "executed_by": "test@example.test",
        "executed_at": "2026-09-10T00:00:00+09:00",
        "evidence_uri": None,
        "evidence_sha256": None,
    }
    response = api.post("/api/provider-conformance-tests", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["conformance_id"]


def _comparison(snapshot_id: str, runs: list[str], conformances: list[str], purpose="test"):
    return {
        "run_ids": runs,
        "conformance_ids": dict(zip(runs, conformances, strict=True)),
        "truth_snapshot_id": snapshot_id,
        "mode": "horizon",
        "horizon": None,
        "policy_version": "evaluation-v2.9",
        "requested_by": "test@example.test",
        "purpose": purpose,
    }


def test_comparison_is_server_computed_content_addressed_and_queryable(tmp_path):
    api, runs, catalog, _, snapshot_id = _fixture(tmp_path)
    experiment_a, definition_a = _experiment(api, snapshot_id, "moving_average_28")
    experiment_b, definition_b = _experiment(api, snapshot_id, "seasonal_naive_7")
    run_a = _completed_run(api, runs, catalog, experiment_a, 9)
    run_b = _completed_run(api, runs, catalog, experiment_b, 11)
    conformance_a = _conformance(api, definition_a)
    conformance_b = _conformance(api, definition_b)
    request = _comparison(snapshot_id, [run_a, run_b], [conformance_a, conformance_b])

    first = api.post("/api/comparisons", json=request)
    second = api.post("/api/comparisons", json=request)

    assert first.status_code == second.status_code == 201
    assert first.json()["comparison_id"] == second.json()["comparison_id"]
    assert first.json()["result"]["official_ranking_ready"] is True
    assert set(first.json()["result"]["official_runs"]) == {run_a, run_b}
    assert len(first.json()["run_evaluations"]) == 2
    assert api.get(f"/api/comparisons?run_id={run_a}").json()[0]["comparison_id"] == (
        first.json()["comparison_id"]
    )
    providers = api.get("/api/providers").json()
    baseline = next(item for item in providers if item["provider_id"] == "builtin-baseline")
    model = next(item for item in baseline["models"] if item["model_id"] == "moving_average_28")
    assert model["fixed_ranking_eligible"] is True


def test_comparison_detail_includes_run_resource_summary(tmp_path):
    api, runs, catalog, _, snapshot_id = _fixture(tmp_path)
    experiment, definition = _experiment(api, snapshot_id, "moving_average_28")
    run_id = _completed_run(api, runs, catalog, experiment, 9)
    resources = SqliteResourceCostStore(tmp_path / "evaluation.sqlite3")
    resources.record_attempt(
        run_id,
        pd.Timestamp("2026-01-01").date(),
        1,
        (ResourceUsage(ResourceMetric.INFERENCE_SECONDS, Decimal("1.25"), "test"),),
    )
    request = _comparison(snapshot_id, [run_id], [_conformance(api, definition)])
    created = api.post("/api/comparisons", json=request)

    detail = api.get(f"/api/comparisons/{created.json()['comparison_id']}")

    assert detail.status_code == 200
    summary = detail.json()["run_evaluations"][0]["resources"]
    inference = next(
        item for item in summary["measurements"] if item["metric"] == "INFERENCE_SECONDS"
    )
    assert inference["quantity"] == "1.25"
    assert "attempt_measurements" not in summary


def test_monthly_retraining_is_reference_only_in_fixed_ranking(tmp_path):
    api, runs, catalog, _, snapshot_id = _fixture(tmp_path)
    fixed_experiment, fixed_definition = _experiment(
        api, snapshot_id, "moving_average_28"
    )
    monthly_experiment, monthly_definition = _experiment(
        api, snapshot_id, "seasonal_naive_7", "MONTHLY_EXPANDING"
    )
    fixed_run = _completed_run(api, runs, catalog, fixed_experiment, 9)
    monthly_run = _completed_run(api, runs, catalog, monthly_experiment, 10)
    request = _comparison(
        snapshot_id,
        [fixed_run, monthly_run],
        [_conformance(api, fixed_definition), _conformance(api, monthly_definition)],
    )

    response = api.post("/api/comparisons", json=request)

    assert response.status_code == 201, response.text
    scores = {
        item["run_id"]: item["score"] for item in response.json()["run_evaluations"]
    }
    assert scores[fixed_run]["official_eligible"] is True
    assert scores[monthly_run]["official_eligible"] is False
    assert scores[monthly_run]["common_metrics"]["wape_pct"] is not None


def test_failed_conformance_keeps_metrics_but_excludes_official_ranking(tmp_path):
    api, runs, catalog, _, snapshot_id = _fixture(tmp_path)
    experiment_a, definition_a = _experiment(api, snapshot_id, "moving_average_28")
    experiment_b, definition_b = _experiment(api, snapshot_id, "seasonal_naive_7")
    run_a = _completed_run(api, runs, catalog, experiment_a, 9)
    run_b = _completed_run(api, runs, catalog, experiment_b, 11)
    request = _comparison(
        snapshot_id,
        [run_a, run_b],
        [_conformance(api, definition_a), _conformance(api, definition_b, failed=True)],
    )

    response = api.post("/api/comparisons", json=request)

    assert response.status_code == 201
    result = response.json()["result"]
    assert result["official_runs"] == [run_a]
    assert result["official_ranking_ready"] is False
    assert result["incomplete_runs"] == []
    assert result["official_excluded_runs"] == [run_b]
    assert response.json()["run_evaluations"][1]["score"]["own_metrics"] is not None


def test_baseline_and_autoets_runs_can_share_an_official_comparison(tmp_path):
    api, runs, catalog, _, snapshot_id = _fixture(tmp_path)
    baseline_experiment, baseline_definition = _experiment(
        api, snapshot_id, "moving_average_28"
    )
    autoets_experiment, autoets_definition = _statsforecast_experiment(api, snapshot_id)
    baseline_run = _completed_run(api, runs, catalog, baseline_experiment, 9)
    autoets_run = _completed_run(api, runs, catalog, autoets_experiment, 11)
    request = _comparison(
        snapshot_id,
        [baseline_run, autoets_run],
        [_conformance(api, baseline_definition), _conformance(api, autoets_definition)],
        purpose="baselineとAutoETSの固定条件比較",
    )

    response = api.post("/api/comparisons", json=request)

    assert response.status_code == 201, response.text
    assert set(response.json()["result"]["official_runs"]) == {
        baseline_run,
        autoets_run,
    }
    assert response.json()["result"]["official_ranking_ready"] is True


def test_comparison_rejects_client_metrics_mismatched_conformance_and_tamper(tmp_path):
    api, runs, catalog, data_path, snapshot_id = _fixture(tmp_path)
    experiment_a, definition_a = _experiment(api, snapshot_id, "moving_average_28")
    experiment_b, definition_b = _experiment(api, snapshot_id, "seasonal_naive_7")
    run_a = _completed_run(api, runs, catalog, experiment_a, 9)
    run_b = _completed_run(api, runs, catalog, experiment_b, 11)
    conformance_a = _conformance(api, definition_a)
    conformance_b = _conformance(api, definition_b)
    request = _comparison(snapshot_id, [run_a, run_b], [conformance_a, conformance_b])

    assert api.post("/api/comparisons", json={**request, "metrics": {}}).status_code == 422
    mismatched = _comparison(snapshot_id, [run_a, run_b], [conformance_b, conformance_a])
    assert api.post("/api/comparisons", json=mismatched).status_code == 409
    data_path.write_text("tampered", encoding="utf-8")
    request["purpose"] = "tamper-check"
    response = api.post("/api/comparisons", json=request)
    assert response.status_code == 422
    assert "checksum" in response.json()["message"]


def test_comparison_rejects_nonterminal_run_and_unknown_record(tmp_path):
    api, runs, _, _, snapshot_id = _fixture(tmp_path)
    experiment, definition = _experiment(api, snapshot_id, "moving_average_28")
    run_id = api.post("/api/runs", json={"experiment_id": experiment}).json()["run_id"]
    conformance = _conformance(api, definition)

    response = api.post(
        "/api/comparisons", json=_comparison(snapshot_id, [run_id], [conformance])
    )

    assert response.status_code == 409
    assert api.get("/api/comparisons/missing").status_code == 404
    assert runs.get_run(run_id).status == "QUEUED"


def test_comparison_rejects_conformance_from_old_provider_version(tmp_path):
    api, runs, catalog, _, snapshot_id = _fixture(tmp_path)
    experiment, definition = _experiment(api, snapshot_id, "moving_average_28")
    run_id = _completed_run(api, runs, catalog, experiment, 9)
    conformance_id = _conformance(api, definition)
    with sqlite3.connect(tmp_path / "evaluation.sqlite3") as database:
        database.execute(
            "UPDATE provider_conformance_tests SET provider_version=? "
            "WHERE conformance_id=?",
            ("old-version", conformance_id),
        )

    response = api.post(
        "/api/comparisons",
        json=_comparison(snapshot_id, [run_id], [conformance_id]),
    )

    assert response.status_code == 409
    assert "現在のProvider適合記録" in response.json()["message"]
