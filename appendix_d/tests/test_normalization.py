"""版付きmapping、行隔離、数量照合、訂正版採用。"""

import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.ingestion import ImportProcessor, SqliteIngestionStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.normalization import (
    NormalizationProcessor,
    SqliteNormalizationStore,
    make_mapping,
)


def mapping_definition():
    return {
        "date_column": "出荷日",
        "jan_column": "JAN",
        "product_name_column": "商品名",
        "quantity_column": "数量",
        "unit_column": "単位",
        "center_column": "センター",
        "row_type_column": "行区分",
        "date_formats": ["%Y/%m/%d"],
        "allowed_units": ["PACK"],
        "availability_mode": "ASSUMED",
        "file_mode": "FULL",
    }


def environment(tmp_path, content):
    inputs = tmp_path / "input"
    inputs.mkdir()
    source = inputs / "shipments.csv"
    source.write_text(content, encoding="utf-8")
    database = tmp_path / "kiban.sqlite3"
    ingestion = SqliteIngestionStore(database)
    imported = ingestion.enqueue("shipments.csv")
    ImportProcessor(ingestion, inputs, tmp_path / "archive").process_next()
    source_file = ingestion.list_files(imported.import_id)[0]
    normalization = SqliteNormalizationStore(database)
    mapping = make_mapping(mapping_definition())
    normalization.put_mapping(mapping)
    return source, ingestion, source_file, normalization, mapping


def test_normalizes_rows_preserves_jan_and_reconciles_quantity(tmp_path):
    content = (
        "出荷日,JAN,商品名,数量,単位,センター,行区分\n"
        "2026/01/01,0012345678901,商品A,4,PACK,C1,SHIPMENT\n"
        "2026/01/02,0012345678902,商品B,-2,PACK,C1,SHIPMENT\n"
        "2026/01/03,0012345678903,商品C,3,BOX,C1,SHIPMENT\n"
        "2026/01/04,0012345678904,商品D,1,PACK,C1,RETURN\n"
    )
    _, ingestion, source_file, store, mapping = environment(tmp_path, content)
    job = store.enqueue(source_file.source_file_id, mapping.mapping_id)
    result = NormalizationProcessor(store, ingestion).process_next()
    assert result.status == "SUCCEEDED"
    assert (result.total_rows, result.accepted_rows, result.quarantined_rows) == (4, 1, 3)
    payload = store.results(job.normalization_id)
    assert payload["rows"][0]["raw_jan"] == "0012345678901"
    assert payload["rows"][0]["available_at"] == "2026-01-02T00:00:00+09:00"
    assert payload["reconciliation"] == {
        "normalization_id": job.normalization_id,
        "parseable_quantity": "6",
        "accepted_quantity": "4",
        "quarantined_quantity": "2",
        "unexplained_quantity": "0",
    }


def test_invalid_quantity_and_date_keep_raw_fields_in_quarantine(tmp_path):
    content = (
        "出荷日,JAN,商品名,数量,単位,センター,行区分\n"
        "bad,000123,商品A,not-a-number,PACK,C1,SHIPMENT\n"
    )
    _, ingestion, source_file, store, mapping = environment(tmp_path, content)
    job = store.enqueue(source_file.source_file_id, mapping.mapping_id)
    NormalizationProcessor(store, ingestion).process_next()
    row = store.results(job.normalization_id)["rows"][0]
    assert row["raw_jan"] == "000123"
    assert row["status"] == "QUARANTINED"
    assert "日付形式" in row["error"] and "数量が数値" in row["error"]


def test_mapping_is_content_addressed_and_observed_requires_timestamp_column(tmp_path):
    first = make_mapping(mapping_definition())
    assert first == make_mapping(mapping_definition())
    changed = mapping_definition()
    changed["allowed_units"] = ["CASE"]
    assert make_mapping(changed).mapping_id != first.mapping_id
    store = SqliteNormalizationStore(tmp_path / "mapping.sqlite3")
    store.put_mapping(first)
    with pytest.raises(ValueError, match="変更できません"):
        store.put_mapping(replace(first, definition={**first.definition, "file_mode": "DELTA"}))
    invalid = mapping_definition()
    invalid["availability_mode"] = "OBSERVED"
    with pytest.raises(ValueError, match="available_at_column"):
        make_mapping(invalid)


def test_fixed_unit_normalizes_csv_without_unit_column(tmp_path):
    content = (
        "出荷日,JAN,商品名,数量,センター,行区分\n"
        "2026/01/01,0012345678901,商品A,4,C1,SHIPMENT\n"
    )
    _, ingestion, source_file, store, _ = environment(tmp_path, content)
    definition = mapping_definition()
    definition.pop("unit_column")
    definition["unit_value"] = "個"
    definition["allowed_units"] = ["個"]
    mapping = make_mapping(definition)
    store.put_mapping(mapping)

    job = store.enqueue(source_file.source_file_id, mapping.mapping_id)
    result = NormalizationProcessor(store, ingestion).process_next()

    assert result.status == "SUCCEEDED"
    row = store.results(job.normalization_id)["rows"][0]
    assert row["status"] == "ACCEPTED"
    assert row["unit"] == "個"


def test_mapping_requires_exactly_one_unit_source():
    missing = mapping_definition()
    missing.pop("unit_column")
    with pytest.raises(ValueError, match="unit_columnとunit_value"):
        make_mapping(missing)
    duplicate = mapping_definition()
    duplicate["unit_value"] = "個"
    with pytest.raises(ValueError, match="unit_columnとunit_value"):
        make_mapping(duplicate)


def test_correction_candidate_requires_explicit_versioned_selection(tmp_path):
    header = "出荷日,JAN,商品名,数量,単位,センター,行区分\n"
    source, ingestion, original, store, mapping = environment(
        tmp_path, header + "2026/01/01,001,商品A,4,PACK,C1,SHIPMENT\n"
    )
    source.write_text(header + "2026/01/01,001,商品A,5,PACK,C1,SHIPMENT\n")
    imported = ingestion.enqueue("shipments.csv")
    ImportProcessor(ingestion, tmp_path / "input", tmp_path / "archive").process_next()
    correction = ingestion.list_files(imported.import_id)[0]
    with pytest.raises(ValueError, match="明示採用"):
        store.enqueue(correction.source_file_id, mapping.mapping_id)
    store.select_source(
        correction.logical_path,
        correction.source_file_id,
        "source-selection-v2",
        "analyst@example.test",
        "訂正された数量を確認",
    )
    selections = store.list_selections("shipments.csv")
    assert selections[0].decided_by == "analyst@example.test"
    assert selections[0].reason == "訂正された数量を確認"
    another_mapping = mapping_definition()
    another_mapping["date_formats"] = ["%Y/%m/%d", "%Y-%m-%d"]
    version = make_mapping(another_mapping)
    store.put_mapping(version)
    with pytest.raises(ValueError, match="明示採用"):
        store.enqueue(original.source_file_id, version.mapping_id)
    job = store.enqueue(correction.source_file_id, mapping.mapping_id)
    NormalizationProcessor(store, ingestion).process_next()
    assert Decimal(store.results(job.normalization_id)["rows"][0]["quantity"]) == Decimal(5)


def test_tampered_archived_source_fails_without_rows(tmp_path):
    content = (
        "出荷日,JAN,商品名,数量,単位,センター,行区分\n2026/01/01,001,商品A,4,PACK,C1,SHIPMENT\n"
    )
    _, ingestion, source_file, store, mapping = environment(tmp_path, content)
    job = store.enqueue(source_file.source_file_id, mapping.mapping_id)
    Path(source_file.stored_path).write_text("tampered")
    result = NormalizationProcessor(store, ingestion).process_next()
    assert result.status == "FAILED"
    assert "checksum" in result.error
    assert store.results(job.normalization_id)["rows"] == []


def test_observed_availability_requires_timezone_and_is_saved_as_utc(tmp_path):
    content = (
        "出荷日,JAN,商品名,数量,単位,センター,行区分,利用可能時刻\n"
        "2026/01/01,001,商品A,4,PACK,C1,SHIPMENT,2026-01-02T09:00:00+09:00\n"
        "2026/01/02,002,商品B,5,PACK,C1,SHIPMENT,2026-01-03T09:00:00\n"
    )
    _, ingestion, source_file, store, _ = environment(tmp_path, content)
    definition = mapping_definition()
    definition["availability_mode"] = "OBSERVED"
    definition["available_at_column"] = "利用可能時刻"
    mapping = make_mapping(definition)
    store.put_mapping(mapping)
    job = store.enqueue(source_file.source_file_id, mapping.mapping_id)
    NormalizationProcessor(store, ingestion).process_next()
    rows = store.results(job.normalization_id)["rows"]
    assert rows[0]["available_at"] == "2026-01-02T00:00:00+00:00"
    assert rows[0]["status"] == "ACCEPTED"
    assert rows[1]["status"] == "QUARANTINED"
    assert "timezone" in rows[1]["error"]


def test_api_to_separate_normalization_worker_and_quality(tmp_path):
    content = (
        "出荷日,JAN,商品名,数量,単位,センター,行区分\n"
        "2026/01/01,0012345678901,商品A,4,PACK,C1,SHIPMENT\n"
    )
    _, ingestion, source_file, normalization, _ = environment(tmp_path, content)
    database = tmp_path / "kiban.sqlite3"
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            ingestion=ingestion,
            normalization=normalization,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    mapping_response = api.post("/api/mappings", json=mapping_definition())
    assert mapping_response.status_code == 201
    mappings = api.get("/api/mappings")
    assert mappings.status_code == 200
    assert mappings.json()[0]["mapping_id"] == mapping_response.json()["id"]
    created = api.post(
        "/api/normalizations",
        json={
            "source_file_id": source_file.source_file_id,
            "mapping_id": mapping_response.json()["id"],
        },
    )
    assert created.status_code == 202
    jobs = api.get("/api/normalizations")
    assert jobs.status_code == 200
    assert jobs.json()[0]["status"] == "QUEUED"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "forecast_provider.normalization_worker",
            "--sqlite",
            str(database),
            "--once",
        ],
        check=True,
    )
    result = api.get(f"/api/normalizations/{created.json()['id']}")
    assert result.status_code == 200
    assert result.json()["accepted_rows"] == 1
    summary = api.get(f"/api/normalizations/{created.json()['id']}/summary")
    assert summary.status_code == 200
    assert summary.json()["reconciliation"]["accepted_quantity"] == "4"
    page = api.get(
        f"/api/normalizations/{created.json()['id']}/row-page",
        params={"status": "ACCEPTED", "limit": 1, "offset": 0},
    )
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["raw_jan"] == "0012345678901"
    assert api.get(
        f"/api/normalizations/{created.json()['id']}/row-page",
        params={"status": "INVALID"},
    ).status_code == 422
    assert api.get("/api/quality").json() == {
        "files": {"ACCEPTED": 1},
        "encodings": {"utf-8": 1},
        "jobs": {"SUCCEEDED": 1},
        "rows": {"ACCEPTED": 1},
        "center_month": [
            {
                "center_id": "C1",
                "month": "2026-01",
                "accepted_rows": 1,
                "quarantined_rows": 0,
                "accepted_quantity": "4",
            }
        ],
        "errors": {},
    }
