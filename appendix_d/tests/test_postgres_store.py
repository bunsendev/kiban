"""PostgreSQL schemaと、接続可能な環境でのRunStore適合確認。"""

import os
import uuid
from pathlib import Path

import pytest
from test_job_resume import expectation, origin, point
from test_run_api import snapshot_payload

from forecast_provider.catalog import PostgresCatalogStore
from forecast_provider.catalog.domain import make_snapshot
from forecast_provider.jobs import OriginOutput, PostgresRunStore, RunDefinition


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
