"""PostgreSQL実DBでのPhase 1K受入技術判定。"""

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from forecast_provider.acceptance import (
    AcceptanceProcessor,
    PostgresAcceptanceStore,
    make_acceptance_case,
)
from forecast_provider.catalog import PostgresCatalogStore
from forecast_provider.catalog.domain import make_snapshot
from forecast_provider.daily import DailyValue, PostgresDailyStore, make_daily_build, series_id
from forecast_provider.daily.export import publish_daily_csv
from forecast_provider.daily.records import encode_json
from forecast_provider.daily.snapshot import snapshot_manifest
from forecast_provider.master import PostgresMasterStore, make_product


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_acceptance_evaluates_real_three_product_case(tmp_path):
    dsn = os.environ["KIBAN_TEST_POSTGRES_DSN"]
    key = uuid.uuid4().hex
    catalog = PostgresCatalogStore(dsn)
    master = PostgresMasterStore(dsn)
    daily = PostgresDailyStore(dsn)
    acceptance = PostgresAcceptanceStore(dsn)
    products = []
    for index in range(3):
        product = make_product(
            f"PostgreSQL受入商品-{key}-{index}",
            "test@example.test",
            "Phase 1K実DB試験",
        )
        master.put_product(product)
        products.append(product)
    definition = {
        "schedule_id": f"schedule-{key}",
        "normalization_ids": [f"normalization-{key}"],
        "mapping_version": f"mapping-{key}",
        "period_version": f"period-{key}",
        "closure_version": None,
        "as_of": "2026-02-04T00:00:00+09:00",
        "selection_version": f"selection-{key}",
        "selected_series": [
            {"canonical_product_id": item.canonical_product_id, "center_id": "C1"}
            for item in products
        ],
        "train_start": "2026-02-01",
        "train_end": "2026-02-02",
        "test_start": "2026-02-03",
        "test_end": "2026-02-03",
        "origin_interval_days": 1,
        "max_horizon": 1,
        "primary_horizon_max": 1,
        "report_horizons": [1],
        "availability_mode": "OBSERVED",
    }
    job = make_daily_build(definition)
    values = []
    for product in products:
        for offset in range(3):
            day = date(2026, 2, 1) + timedelta(days=offset)
            values.append(
                DailyValue(
                    job.build_id,
                    product.canonical_product_id,
                    "C1",
                    day.isoformat(),
                    series_id(product.canonical_product_id, "C1"),
                    Decimal(offset + 1),
                    Decimal(offset + 1),
                    "OBSERVED",
                    datetime(2026, 2, 4, tzinfo=UTC).isoformat(),
                )
            )
    data_uri, data_sha = publish_daily_csv(values, tmp_path / "snapshots")
    snapshot = make_snapshot(snapshot_manifest(job, values, data_uri, data_sha))
    catalog.put_snapshot(snapshot)
    with daily._connect() as db:
        db.execute(
            "INSERT INTO daily_build_jobs("
            "build_id,format_version,condition_fingerprint,definition_json,status,"
            "snapshot_id,data_uri,data_sha256"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                job.build_id,
                job.format_version,
                job.condition_fingerprint,
                encode_json(job.definition),
                "RUNNING",
                None,
                None,
                None,
            ),
        )
    daily.complete(job.build_id, [], values, snapshot.snapshot_id, data_uri, data_sha)
    payload = {
        "acceptance_version": f"acceptance-{key}",
        "daily_build_id": job.build_id,
        "data_kind": "REAL",
        "expected_product_ids": [item.canonical_product_id for item in products],
        "required_availability_mode": "OBSERVED",
        "min_usable_days_per_series": 3,
        "max_missing_rate": 0,
        "max_partial_invalid_rate": 0,
        "requested_by": "test@example.test",
        "purpose": "Phase 1K実DB試験",
    }
    case = make_acceptance_case(payload)
    acceptance.put_case(case)
    result = AcceptanceProcessor(
        acceptance, daily, catalog, tmp_path / "reports"
    ).process_next()
    assert result.status == "SUCCEEDED"
    assert result.outcome == "PASSED"
    assert case.case_id in {item.case_id for item in acceptance.list_cases()}
    assert all(item.status == "PASSED" for item in acceptance.list_checks(case.case_id))
