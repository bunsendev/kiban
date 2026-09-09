"""PostgreSQL schemaと、接続可能な環境でのRunStore適合確認。"""

import os
import uuid
from pathlib import Path

import pytest
from test_job_resume import expectation, origin, point
from test_run_api import snapshot_payload

from forecast_provider.catalog import PostgresCatalogStore
from forecast_provider.catalog.domain import make_snapshot
from forecast_provider.ingestion import PostgresIngestionStore
from forecast_provider.jobs import OriginOutput, PostgresRunStore, RunDefinition
from forecast_provider.master import PostgresMasterStore, make_product
from forecast_provider.normalization import PostgresNormalizationStore, make_mapping


def test_postgres_migration_has_locking_and_business_constraints():
    path = (
        Path(__file__).parents[1]
        / "forecast_provider"
        / "jobs"
        / "migrations"
        / "001_run_ledger.sql"
    )
    sql = path.read_text(encoding="utf-8")
    assert "TIMESTAMPTZ" in sql
    assert "uq_forecast_point" in sql
    assert "uq_forecast_quantile" in sql
    assert "FOREIGN KEY(run_id, origin_date)" in sql
    catalog_sql = path.parents[2] / "catalog" / "schema.sql"
    text = catalog_sql.read_text(encoding="utf-8")
    assert "dataset_snapshots" in text and "experiments" in text
    ingestion_sql = path.parents[2] / "ingestion" / "schema.sql"
    text = ingestion_sql.read_text(encoding="utf-8")
    assert "import_jobs" in text and "source_files" in text
    assert "UNIQUE(import_id, logical_path)" in text
    normalization_sql = path.parents[2] / "normalization" / "schema.sql"
    text = normalization_sql.read_text(encoding="utf-8")
    assert "column_mappings" in text and "shipment_rows" in text
    assert "quantity_reconciliations" in text and "source_file_selections" in text
    master_sql = path.parents[2] / "master" / "schema.sql"
    text = master_sql.read_text(encoding="utf-8")
    assert "matching_candidates" in text and "matching_decisions" in text
    assert "jan_mappings_lookup_idx" in text and "handling_periods_lookup_idx" in text
    assert "left_product_id=right_product_id" in text
    postgres_store = (path.parents[2] / "master" / "postgres_store.py").read_text(encoding="utf-8")
    assert "FOR UPDATE SKIP LOCKED" in postgres_store
    assert postgres_store.count("pg_advisory_xact_lock") == 2


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_store_conforms_to_origin_transaction_contract():
    store = PostgresRunStore(os.environ["KIBAN_TEST_POSTGRES_DSN"])
    run_id = f"phase1d-{uuid.uuid4()}"
    store.create_run(
        RunDefinition(run_id, "experiment", "fingerprint", "builtin-baseline", "ma", 1),
        (origin(1),),
        (expectation(1),),
    )
    store.start_or_resume(run_id, "fingerprint")
    lease = store.claim_next_origin(run_id, "worker", 60)
    assert lease is not None
    store.complete_origin(lease, OriginOutput((point(1),)))
    assert store.finish_run(run_id) == "SUCCEEDED"
    catalog = PostgresCatalogStore(os.environ["KIBAN_TEST_POSTGRES_DSN"])
    snapshot = make_snapshot(snapshot_payload())
    catalog.put_snapshot(snapshot)
    assert catalog.get_snapshot(snapshot.snapshot_id) == snapshot
    ingestion = PostgresIngestionStore(os.environ["KIBAN_TEST_POSTGRES_DSN"])
    job = ingestion.enqueue(f"phase1g-{uuid.uuid4()}.csv")
    assert ingestion.claim().import_id == job.import_id
    ingestion.finish(job.import_id)
    assert ingestion.get_job(job.import_id).status == "SUCCEEDED"
    normalization = PostgresNormalizationStore(os.environ["KIBAN_TEST_POSTGRES_DSN"])
    mapping = make_mapping(
        {
            "date_column": "date",
            "jan_column": "jan",
            "product_name_column": "name",
            "quantity_column": "quantity",
            "unit_column": "unit",
            "center_value": "C1",
            "date_formats": ["%Y-%m-%d"],
            "allowed_units": ["PACK"],
            "availability_mode": "ASSUMED",
            "file_mode": "FULL",
        }
    )
    normalization.put_mapping(mapping)
    assert normalization.get_mapping(mapping.mapping_id) == mapping
    master = PostgresMasterStore(os.environ["KIBAN_TEST_POSTGRES_DSN"])
    product = make_product(
        f"PostgreSQL確認-{uuid.uuid4()}", "test@example.test", "live store適合確認"
    )
    master.put_product(product)
    assert any(
        value["canonical_product_id"] == product.canonical_product_id
        for value in master.list_products()
    )
