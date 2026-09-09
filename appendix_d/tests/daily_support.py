"""Phase 1J適合試験で共有する上流データ準備。"""

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

HEADER = "出荷日,JAN,商品名,数量,単位,センター,行区分\n"


def mapping_definition():
    return {
        "date_column": "出荷日",
        "jan_column": "JAN",
        "product_name_column": "商品名",
        "quantity_column": "数量",
        "unit_column": "単位",
        "center_column": "センター",
        "row_type_column": "行区分",
        "date_formats": ["%Y-%m-%d"],
        "allowed_units": ["PACK"],
        "availability_mode": "ASSUMED",
        "file_mode": "FULL",
    }


def normalize_files(tmp_path, database, contents):
    inputs = tmp_path / "input"
    archive = tmp_path / "archive"
    inputs.mkdir()
    ingestion = SqliteIngestionStore(database)
    normalization = SqliteNormalizationStore(database)
    mapping = make_mapping(mapping_definition())
    normalization.put_mapping(mapping)
    jobs = []
    for logical_path, content in contents.items():
        (inputs / logical_path).write_text(content, encoding="utf-8")
        imported = ingestion.enqueue(logical_path)
        ImportProcessor(ingestion, inputs, archive).process_next()
        source = ingestion.list_files(imported.import_id)[0]
        job = normalization.enqueue(source.source_file_id, mapping.mapping_id)
        NormalizationProcessor(normalization, ingestion).process_next()
        jobs.append(job)
    return jobs


def create_master(database):
    master = SqliteMasterStore(database)
    product = make_product("日次商品", "master@example.test", "日次集計対象")
    master.put_product(product)
    master.put_jan_mapping(
        make_jan_mapping(
            "001",
            product.canonical_product_id,
            "2026-01-01",
            None,
            "mapping-v1",
            "master@example.test",
            "JAN確認",
        )
    )
    master.put_handling_period(
        make_handling_period(
            product.canonical_product_id,
            "C1",
            "2026-01-01",
            "2026-01-05",
            "CONFIRMED",
            "period-v1",
            "master@example.test",
            "取扱表を確認",
        )
    )
    return master, product


def schedule_payload():
    return {
        "schedule_version": "schedule-v1",
        "valid_from": "2026-01-01",
        "valid_to": "2026-01-06",
        "files": [
            {
                "logical_path": f"day{day}.csv",
                "center_id": "C1",
                "file_type": "SHIPMENT",
                "target_start": f"2026-01-0{day}",
                "target_end": f"2026-01-0{day}",
                "absence_means_zero": day != 3,
            }
            for day in (1, 2, 3, 4, 5)
        ],
    }


def build_payload(schedule_id, normalization_ids, product_id):
    return {
        "schedule_id": schedule_id,
        "normalization_ids": normalization_ids,
        "mapping_version": "mapping-v1",
        "period_version": "period-v1",
        "closure_version": "closure-v1",
        "as_of": "2026-01-07T00:00:00+09:00",
        "selection_version": "selection-v1",
        "selected_series": [{"canonical_product_id": product_id, "center_id": "C1"}],
        "train_start": "2026-01-01",
        "train_end": "2026-01-03",
        "test_start": "2026-01-04",
        "test_end": "2026-01-06",
        "origin_interval_days": 1,
        "max_horizon": 2,
        "primary_horizon_max": 2,
        "report_horizons": [1, 2],
        "availability_mode": "ASSUMED",
    }
