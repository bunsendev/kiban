"""PostgreSQL実DBでのPhase 1L候補算出と選定版管理。"""

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from forecast_provider.daily import DailyValue, PostgresDailyStore, make_daily_build, series_id
from forecast_provider.daily.records import encode_json
from forecast_provider.master import PostgresMasterStore, make_jan_mapping, make_product
from forecast_provider.selection import (
    PostgresSelectionStore,
    SelectionProcessor,
    make_candidate_job,
    make_selection,
)


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_candidate_job_and_selection_are_persisted():
    dsn = os.environ["KIBAN_TEST_POSTGRES_DSN"]
    key = uuid.uuid4().hex
    master = PostgresMasterStore(dsn)
    daily = PostgresDailyStore(dsn)
    products = [
        make_product(f"選定実DB商品-{key}-{index}", "test@example.test", "Phase 1L実DB試験")
        for index in range(3)
    ]
    for index, product in enumerate(products):
        master.put_product(product)
        master.put_jan_mapping(
            make_jan_mapping(
                f"jan-{key}-{index}",
                product.canonical_product_id,
                "2026-03-01",
                None,
                f"mapping-{key}",
                "test@example.test",
                "Phase 1L実DB試験",
            )
        )
    definition = {
        "schedule_id": f"schedule-{key}",
        "normalization_ids": [f"normalization-{key}"],
        "mapping_version": f"mapping-{key}",
        "period_version": f"period-{key}",
        "closure_version": None,
        "as_of": "2026-03-04T00:00:00+09:00",
        "selection_version": f"candidate-universe-{key}",
        "selected_series": [
            {"canonical_product_id": product.canonical_product_id, "center_id": "C1"}
            for product in products
        ],
        "train_start": "2026-03-01",
        "train_end": "2026-03-02",
        "test_start": "2026-03-03",
        "test_end": "2026-03-03",
        "origin_interval_days": 1,
        "max_horizon": 1,
        "primary_horizon_max": 1,
        "report_horizons": [1],
        "availability_mode": "OBSERVED",
    }
    build = make_daily_build(definition)
    values = []
    for product_index, product in enumerate(products):
        for offset in range(3):
            day = date(2026, 3, 1) + timedelta(days=offset)
            quantity = Decimal(product_index + offset + 1)
            values.append(
                DailyValue(
                    build.build_id,
                    product.canonical_product_id,
                    "C1",
                    day.isoformat(),
                    series_id(product.canonical_product_id, "C1"),
                    quantity,
                    quantity,
                    "OBSERVED",
                    datetime(2026, 3, 4, tzinfo=UTC).isoformat(),
                )
            )
    with daily._connect() as db:
        db.execute(
            "INSERT INTO daily_build_jobs("
            "build_id,format_version,condition_fingerprint,definition_json,status"
            ") VALUES (?,?,?,?,?)",
            (
                build.build_id,
                build.format_version,
                build.condition_fingerprint,
                encode_json(build.definition),
                "SUCCEEDED",
            ),
        )
        db.executemany(
            "INSERT INTO daily_values VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    item.build_id,
                    item.canonical_product_id,
                    item.center_id,
                    item.ds,
                    item.unique_id,
                    str(item.raw_quantity),
                    str(item.y),
                    item.state,
                    item.available_at,
                    item.issue,
                )
                for item in values
            ],
        )
    store = PostgresSelectionStore(dsn)
    candidate_job = make_candidate_job(
        {
            "candidate_version": f"candidate-{key}",
            "daily_build_id": build.build_id,
            "business_product_ids": [products[0].canonical_product_id],
            "max_missing_rate": 0,
            "stable_cv_max": 1,
            "intermittent_zero_rate_min": 0.5,
            "requested_by": "test@example.test",
            "purpose": "Phase 1L実DB試験",
        }
    )
    store.put_candidate_job(candidate_job)
    assert SelectionProcessor(store, daily).process_next().status == "SUCCEEDED"
    candidates = store.list_candidates(candidate_job.candidate_job_id)
    assert len(candidates) == 3
    selection = make_selection(
        {
            "selection_version": f"selection-{key}",
            "candidate_job_id": candidate_job.candidate_job_id,
            "scope": "INITIAL",
            "items": [
                {
                    "canonical_product_id": product.canonical_product_id,
                    "center_ids": ["C1"],
                    "reason": "実DB選定試験",
                }
                for product in products
            ],
            "selected_by": "test@example.test",
            "rationale": "Phase 1L実DB試験",
        }
    )
    saved = store.put_selection(selection)
    assert saved.selection_id == selection.selection_id
    assert len(store.list_selection_items(selection.selection_id)) == 3
