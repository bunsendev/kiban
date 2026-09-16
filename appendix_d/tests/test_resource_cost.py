"""Phase 3B: Provider共通の資源・費用台帳。"""

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.api.security import TokenAuthenticator
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import (
    Expectation,
    ForecastValue,
    OriginDefinition,
    OriginOutput,
    RunDefinition,
    SqliteRunStore,
    resume_run,
)
from forecast_provider.resource_cost import (
    ResourceMetric,
    ResourceUsage,
    SqliteResourceCostStore,
    make_unit_price,
)


def _stores(tmp_path, run_id="run-resource"):
    database = tmp_path / "resource.sqlite3"
    runs = SqliteRunStore(database)
    day = date(2026, 1, 1)
    runs.create_run(
        RunDefinition(run_id, "experiment-1", "fingerprint-1", "provider-a", "model-a", 7),
        (OriginDefinition(day, datetime(2026, 1, 2, tzinfo=UTC)),),
        (Expectation("A", day, date(2026, 1, 2), 1),),
    )
    return runs, SqliteResourceCostStore(database), database


def _price(metric, amount="0.5", provider_id="*"):
    return make_unit_price(
        provider_id=provider_id,
        metric=metric,
        unit_price=Decimal(amount),
        currency="JPY",
        retrieved_on=date(2026, 9, 16),
        source_ref="社内単価表2026-09",
        created_by="admin@example.test",
    )


def test_measurements_are_attempt_idempotent_and_artifacts_are_run_deduplicated(tmp_path):
    _, costs, _ = _stores(tmp_path)
    day = date(2026, 1, 1)
    usages = (
        ResourceUsage(ResourceMetric.INFERENCE_SECONDS, Decimal("2.5"), "worker_total"),
        ResourceUsage(ResourceMetric.PEAK_MEMORY_BYTES, Decimal("256"), "process_peak"),
        ResourceUsage(
            ResourceMetric.STORAGE_BYTES,
            Decimal("128"),
            "model_artifact",
            "artifact:abc",
        ),
    )

    first = costs.record_attempt("run-resource", day, 1, usages)
    repeated = costs.record_attempt("run-resource", day, 1, usages)
    costs.record_attempt(
        "run-resource",
        day,
        2,
        (
            usages[2],
            ResourceUsage(
                ResourceMetric.PEAK_MEMORY_BYTES, Decimal("512"), "process_peak"
            ),
        ),
    )

    assert [item.measurement_id for item in first] == [
        item.measurement_id for item in repeated
    ]
    summary = costs.summarize("run-resource")
    values = {item["metric"]: item for item in summary["measurements"]}
    assert values["INFERENCE_SECONDS"]["quantity"] == "2.5"
    assert values["STORAGE_BYTES"]["quantity"] == "128"
    assert values["PEAK_MEMORY_BYTES"]["quantity"] == "512"
    assert summary["pricing_complete"] is False
    assert summary["total_cost_amount"] is None


def test_latest_provider_price_precedes_global_and_unknown_price_stays_null(tmp_path):
    _, costs, _ = _stores(tmp_path)
    costs.record_attempt(
        "run-resource",
        date(2026, 1, 1),
        1,
        (
            ResourceUsage(ResourceMetric.CPU_SECONDS, Decimal("4"), "process_cpu"),
            ResourceUsage(ResourceMetric.GPU_SECONDS, Decimal("3"), "gpu_runtime"),
        ),
    )
    costs.put_unit_price(_price(ResourceMetric.CPU_SECONDS, "0.5"))
    costs.put_unit_price(_price(ResourceMetric.CPU_SECONDS, "0.75", "provider-a"))

    summary = costs.summarize("run-resource")
    values = {item["metric"]: item for item in summary["measurements"]}
    assert values["CPU_SECONDS"]["unit_price"] == "0.75"
    assert values["CPU_SECONDS"]["cost_amount"] == "3.00"
    assert values["GPU_SECONDS"]["unit_price"] is None
    assert values["GPU_SECONDS"]["cost_amount"] is None
    assert summary["pricing_complete"] is False
    assert summary["total_cost_amount"] is None


def test_worker_records_successful_attempt_without_changing_executor_contract(tmp_path):
    runs, costs, _ = _stores(tmp_path)

    def execute(lease):
        day = lease.origin.origin_date
        return OriginOutput(
            (
                ForecastValue(
                    "A",
                    day,
                    date(2026, 1, 2),
                    1,
                    "POINT",
                    None,
                    Decimal("1"),
                    Decimal("1"),
                ),
            )
        )

    status = resume_run(
        runs,
        "run-resource",
        "fingerprint-1",
        execute,
        resource_cost=costs,
    )

    assert status == "SUCCEEDED"
    summary = costs.summarize("run-resource")
    measured = {
        item["metric"] for item in summary["measurements"] if item["quantity"] is not None
    }
    assert {"INFERENCE_SECONDS", "CPU_SECONDS"}.issubset(measured)


def test_partial_run_keeps_resource_trace_for_success_and_failure(tmp_path):
    database = tmp_path / "partial.sqlite3"
    runs = SqliteRunStore(database)
    origins = tuple(
        OriginDefinition(
            date(2026, 1, day), datetime(2026, 1, day + 1, tzinfo=UTC)
        )
        for day in (1, 2)
    )
    runs.create_run(
        RunDefinition("run-partial", "experiment-1", "fp", "provider-a", "model-a", 7),
        origins,
        tuple(
            Expectation(
                "A",
                item.origin_date,
                item.origin_date.replace(day=item.origin_date.day + 1),
                1,
            )
            for item in origins
        ),
    )
    costs = SqliteResourceCostStore(database)

    def execute(lease):
        if lease.origin.origin_date.day == 2:
            raise RuntimeError("expected failure")
        return OriginOutput(
            (
                ForecastValue(
                    "A",
                    lease.origin.origin_date,
                    date(2026, 1, 2),
                    1,
                    "POINT",
                    None,
                    Decimal("1"),
                    Decimal("1"),
                ),
            )
        )

    assert resume_run(runs, "run-partial", "fp", execute, resource_cost=costs) == "PARTIAL"
    summary = costs.summarize("run-partial", include_attempts=True)
    inference_attempts = [
        item
        for item in summary["attempt_measurements"]
        if item["metric"] == "INFERENCE_SECONDS"
    ]
    assert {(item["origin_date"], item["attempt"]) for item in inference_attempts} == {
        ("2026-01-01", 1),
        ("2026-01-02", 1),
    }


def test_run_resource_api_and_admin_only_price_registration(tmp_path):
    runs, costs, database = _stores(tmp_path)
    authenticator = TokenAuthenticator.from_json(
        "["
        '{"token":"admin-token-000000000000000000000","subject":"admin@test",'
        '"roles":["ADMIN"]},'
        '{"token":"analyst-token-0000000000000000000","subject":"analyst@test",'
        '"roles":["ANALYST"]}'
        "]"
    )
    api = TestClient(
        create_app(
            runs,
            SqliteCatalogStore(database),
            authenticator,
            resource_cost=costs,
        )
    )
    admin = {"Authorization": "Bearer admin-token-000000000000000000000"}
    analyst = {"Authorization": "Bearer analyst-token-0000000000000000000"}
    request = {
        "provider_id": "*",
        "metric": "CPU_SECONDS",
        "unit_price": "0.5",
        "currency": "jpy",
        "retrieved_on": "2026-09-16",
        "source_ref": "社内単価表",
        "created_by": "spoofed@test",
    }

    assert api.post("/api/resource-unit-prices", json=request, headers=analyst).status_code == 403
    created = api.post("/api/resource-unit-prices", json=request, headers=admin)
    assert created.status_code == 201, created.text
    assert created.json()["created_by"] == "admin@test"
    assert created.json()["currency"] == "JPY"
    run = api.get("/api/runs/run-resource", headers=admin)
    assert run.status_code == 200
    assert run.json()["resources"]["run_id"] == "run-resource"
    assert api.get("/api/runs/missing/resources", headers=admin).status_code == 404
