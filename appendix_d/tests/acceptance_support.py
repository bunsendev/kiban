"""Phase 1K適合試験で共有する匿名3品目の日次build。"""

from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.daily import (
    DailyProcessor,
    SqliteDailyStore,
    make_daily_build,
    make_file_schedule,
)
from forecast_provider.ingestion import ImportProcessor, SqliteIngestionStore
from forecast_provider.master import (
    SqliteMasterStore,
    make_handling_period,
    make_jan_mapping,
    make_product,
)
from forecast_provider.normalization import (
    NormalizationProcessor,
    SqliteNormalizationStore,
    make_mapping,
)

HEADER = "出荷日,JAN,商品名,数量,単位,センター\n"


def build_three_product_daily(tmp_path, database):
    input_root = tmp_path / "input"
    archive_root = tmp_path / "archive"
    output_root = tmp_path / "snapshots"
    input_root.mkdir()
    files = {
        "day1.csv": HEADER
        + "2026-01-01,001,安定品,10,PACK,C1\n"
        + "2026-01-01,002,間欠品,1,PACK,C1\n"
        + "2026-01-01,003,JAN変更品,5,PACK,C1\n",
        "day2.csv": HEADER,
        "day3.csv": HEADER
        + "2026-01-03,001,安定品,12,PACK,C1\n"
        + "2026-01-03,002,間欠品,2,PACK,C1\n"
        + "2026-01-03,003,JAN変更品,4,PACK,C1\n",
    }
    ingestion = SqliteIngestionStore(database)
    normalization = SqliteNormalizationStore(database)
    mapping = make_mapping(
        {
            "date_column": "出荷日",
            "jan_column": "JAN",
            "product_name_column": "商品名",
            "quantity_column": "数量",
            "unit_column": "単位",
            "center_value": "C1",
            "date_formats": ["%Y-%m-%d"],
            "allowed_units": ["PACK"],
            "availability_mode": "ASSUMED",
            "file_mode": "FULL",
        }
    )
    normalization.put_mapping(mapping)
    normalization_ids = []
    for logical_path, content in files.items():
        (input_root / logical_path).write_text(content, encoding="utf-8")
        imported = ingestion.enqueue(logical_path)
        ImportProcessor(ingestion, input_root, archive_root).process_next()
        source = ingestion.list_files(imported.import_id)[0]
        job = normalization.enqueue(source.source_file_id, mapping.mapping_id)
        NormalizationProcessor(normalization, ingestion).process_next()
        normalization_ids.append(job.normalization_id)

    master = SqliteMasterStore(database)
    products = []
    for jan, name in (("001", "安定品"), ("002", "間欠品"), ("003", "JAN変更品")):
        product = make_product(name, "test@example.test", "匿名3品目受入fixture")
        products.append(product)
        master.put_product(product)
        master.put_jan_mapping(
            make_jan_mapping(
                jan,
                product.canonical_product_id,
                "2026-01-01",
                None,
                "mapping-v1",
                "test@example.test",
                "匿名fixture",
            )
        )
        master.put_handling_period(
            make_handling_period(
                product.canonical_product_id,
                "C1",
                "2026-01-01",
                "2026-01-03",
                "CONFIRMED",
                "period-v1",
                "test@example.test",
                "匿名fixture",
            )
        )
    schedule = make_file_schedule(
        {
            "schedule_version": "schedule-v1",
            "valid_from": "2026-01-01",
            "valid_to": "2026-01-03",
            "files": [
                {
                    "logical_path": f"day{day}.csv",
                    "center_id": "C1",
                    "file_type": "SHIPMENT",
                    "target_start": f"2026-01-0{day}",
                    "target_end": f"2026-01-0{day}",
                    "absence_means_zero": True,
                }
                for day in (1, 2, 3)
            ],
        }
    )
    catalog = SqliteCatalogStore(database)
    daily = SqliteDailyStore(database)
    daily.put_schedule(schedule)
    definition = {
        "schedule_id": schedule.schedule_id,
        "normalization_ids": normalization_ids,
        "mapping_version": "mapping-v1",
        "period_version": "period-v1",
        "closure_version": None,
        "as_of": "2026-01-04T00:00:00+09:00",
        "selection_version": "initial-3-products-v1",
        "selected_series": [
            {"canonical_product_id": value.canonical_product_id, "center_id": "C1"}
            for value in products
        ],
        "train_start": "2026-01-01",
        "train_end": "2026-01-02",
        "test_start": "2026-01-03",
        "test_end": "2026-01-03",
        "origin_interval_days": 1,
        "max_horizon": 1,
        "primary_horizon_max": 1,
        "report_horizons": [1],
        "availability_mode": "ASSUMED",
    }
    job = make_daily_build(definition)
    daily.put_job(job)
    result = DailyProcessor(daily, catalog, output_root).process_next()
    assert result.status == "SUCCEEDED"
    return daily, catalog, products, result


def acceptance_payload(build_id, products, data_kind="ANONYMIZED"):
    return {
        "acceptance_version": "acceptance-v1",
        "daily_build_id": build_id,
        "data_kind": data_kind,
        "expected_product_ids": [value.canonical_product_id for value in products],
        "required_availability_mode": "ASSUMED",
        "min_usable_days_per_series": 3,
        "max_missing_rate": 0,
        "max_partial_invalid_rate": 0,
        "requested_by": "operator@example.test",
        "purpose": "少数品目の受入手順確認",
    }
