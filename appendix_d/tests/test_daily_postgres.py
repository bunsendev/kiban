"""PostgreSQL実DBでの日次build適合試験。"""

import os
import uuid

import pytest

from forecast_provider.catalog import PostgresCatalogStore
from forecast_provider.daily import (
    DailyProcessor,
    PostgresDailyStore,
    make_closed_day,
    make_daily_build,
    make_file_schedule,
)
from forecast_provider.ingestion import ImportProcessor, PostgresIngestionStore
from forecast_provider.master import (
    PostgresMasterStore,
    make_handling_period,
    make_jan_mapping,
    make_product,
)
from forecast_provider.normalization import (
    NormalizationProcessor,
    PostgresNormalizationStore,
    make_mapping,
)


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_daily_build_publishes_snapshot(tmp_path):
    dsn = os.environ["KIBAN_TEST_POSTGRES_DSN"]
    key = uuid.uuid4().hex
    logical_path = f"daily-{key}.csv"
    jan = f"jan-{key}"
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / logical_path).write_text(
        f"出荷日,JAN,商品名,数量,単位,センター\n2026-02-01,{jan},PostgreSQL商品,2,PACK,C1\n",
        encoding="utf-8",
    )
    ingestion = PostgresIngestionStore(dsn)
    imported = ingestion.enqueue(logical_path)
    ImportProcessor(ingestion, inputs, tmp_path / "archive").process_next()
    source = ingestion.list_files(imported.import_id)[0]
    normalization = PostgresNormalizationStore(dsn)
    mapping = make_mapping(
        {
            "date_column": "出荷日",
            "jan_column": "JAN",
            "product_name_column": "商品名",
            "quantity_column": "数量",
            "unit_column": "単位",
            "center_column": "センター",
            "date_formats": ["%Y-%m-%d"],
            "allowed_units": ["PACK"],
            "availability_mode": "ASSUMED",
            "file_mode": "FULL",
        }
    )
    normalization.put_mapping(mapping)
    normalized = normalization.enqueue(source.source_file_id, mapping.mapping_id)
    NormalizationProcessor(normalization, ingestion).process_next()
    master = PostgresMasterStore(dsn)
    product = make_product("PostgreSQL商品", "test@example.test", "実DB日次試験")
    master.put_product(product)
    mapping_version = f"mapping-{key}"
    period_version = f"period-{key}"
    master.put_jan_mapping(
        make_jan_mapping(
            jan,
            product.canonical_product_id,
            "2026-02-01",
            None,
            mapping_version,
            "test@example.test",
            "実DB日次試験",
        )
    )
    master.put_handling_period(
        make_handling_period(
            product.canonical_product_id,
            "C1",
            "2026-02-01",
            None,
            "CONFIRMED",
            period_version,
            "test@example.test",
            "実DB日次試験",
        )
    )
    catalog = PostgresCatalogStore(dsn)
    daily = PostgresDailyStore(dsn)
    closure_version = f"closure-{key}"
    daily.put_closed_day(
        make_closed_day(
            "C1",
            "2026-02-02",
            closure_version,
            "2026-01-01T00:00:00+09:00",
            "test@example.test",
            "実DB休業日試験",
        )
    )
    schedule = make_file_schedule(
        {
            "schedule_version": f"schedule-{key}",
            "valid_from": "2026-02-01",
            "valid_to": "2026-02-02",
            "files": [
                {
                    "logical_path": logical_path,
                    "center_id": "C1",
                    "file_type": "SHIPMENT",
                    "target_start": "2026-02-01",
                    "target_end": "2026-02-02",
                    "absence_means_zero": True,
                }
            ],
        }
    )
    daily.put_schedule(schedule)
    job = make_daily_build(
        {
            "schedule_id": schedule.schedule_id,
            "normalization_ids": [normalized.normalization_id],
            "mapping_version": mapping_version,
            "period_version": period_version,
            "closure_version": closure_version,
            "as_of": "2026-02-03T00:00:00+09:00",
            "selection_version": f"selection-{key}",
            "selected_series": [
                {"canonical_product_id": product.canonical_product_id, "center_id": "C1"}
            ],
            "train_start": "2026-02-01",
            "train_end": "2026-02-01",
            "test_start": "2026-02-02",
            "test_end": "2026-02-02",
            "origin_interval_days": 1,
            "max_horizon": 1,
            "primary_horizon_max": 1,
            "report_horizons": [1],
            "availability_mode": "ASSUMED",
        }
    )
    daily.put_job(job)
    result = DailyProcessor(daily, catalog, tmp_path / "snapshots").process_next()
    assert result.status == "SUCCEEDED"
    assert [item.state for item in daily.list_values(job.build_id)] == ["OBSERVED", "CLOSED"]
    snapshot = catalog.get_snapshot(result.snapshot_id)
    assert snapshot.manifest["provenance"]["daily_build_id"] == job.build_id
