"""PostgreSQL schemaと、接続可能な環境でのRunStore適合確認。"""

import os
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from test_job_resume import expectation, origin, point
from test_run_api import snapshot_payload

from forecast_provider.acceptance import PostgresAcceptanceStore
from forecast_provider.catalog import PostgresCatalogStore
from forecast_provider.catalog.domain import make_experiment, make_snapshot
from forecast_provider.comparison_campaign import (
    CampaignEntry,
    PostgresComparisonCampaignStore,
)
from forecast_provider.evaluation_registry import (
    REQUIRED_CHECKS,
    PostgresEvaluationRegistryStore,
    RunEvaluation,
    make_comparison_record,
    make_conformance,
)
from forecast_provider.ingestion import PostgresIngestionStore, SourceFile
from forecast_provider.jobs import OriginOutput, PostgresRunStore, RunDefinition
from forecast_provider.jobs.postgres_store import _HybridRow
from forecast_provider.master import PostgresMasterStore, make_matching_job, make_product
from forecast_provider.model_review import PostgresModelReviewStore
from forecast_provider.normalization import (
    PostgresNormalizationStore,
    Reconciliation,
    ShipmentRow,
    make_mapping,
)
from forecast_provider.provider_conformance import PostgresConformanceJobStore
from forecast_provider.registry import registry
from forecast_provider.reporting import (
    PostgresReportingStore,
    make_adoption,
    make_export_record,
)
from forecast_provider.resource_cost import ResourceMetric, ResourceUsage, make_unit_price
from forecast_provider.resource_cost.postgres_store import PostgresResourceCostStore
from forecast_provider.worker_status import PostgresWorkerStatusStore, WorkerState


def test_postgres_row_uses_sqlite_compatible_temporal_and_uuid_values():
    token = uuid.uuid4()
    row = _HybridRow(
        {
            "origin_date": date(2026, 1, 1),
            "cutoff_at": datetime(2026, 1, 1, tzinfo=UTC),
            "lease_token": token,
        }
    )

    assert row["origin_date"] == "2026-01-01"
    assert row["cutoff_at"] == "2026-01-01T00:00:00+00:00"
    assert row["lease_token"] == str(token)
    assert row[0] == row["origin_date"]


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
    assert "ix_forecast_runs_runnable_provider" in sql
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
    daily_sql = path.parents[2] / "daily" / "schema.sql"
    text = daily_sql.read_text(encoding="utf-8")
    assert "daily_file_completeness" in text and "daily_values" in text
    assert "PARTIAL_OR_INVALID" in text and "zero_confirmable" in text
    upgrade = (path.parents[2] / "daily" / "postgres_upgrade.sql").read_text(encoding="utf-8")
    assert upgrade.count("ADD COLUMN IF NOT EXISTS available_at") == 2
    postgres_store = (path.parents[2] / "master" / "postgres_store.py").read_text(encoding="utf-8")
    assert "FOR UPDATE SKIP LOCKED" in postgres_store
    assert postgres_store.count("pg_advisory_xact_lock") == 2
    daily_store = (path.parents[2] / "daily" / "postgres_store.py").read_text(encoding="utf-8")
    assert "FOR UPDATE SKIP LOCKED" in daily_store
    evaluation_sql = path.parents[2] / "evaluation_registry" / "schema.sql"
    text = evaluation_sql.read_text(encoding="utf-8")
    assert "provider_conformance_tests" in text and "comparison_reports" in text
    assert "comparison_runs" in text and "evaluation_scope_hash" in text
    reporting_sql = path.parents[2] / "reporting" / "schema.sql"
    text = reporting_sql.read_text(encoding="utf-8")
    assert "report_exports" in text and "adoption_records" in text
    assert "UNIQUE(comparison_id,export_version)" in text
    assert text.count("REFERENCES forecast_runs(run_id)") == 3
    resource_sql = path.parents[2] / "resource_cost" / "schema_postgres.sql"
    text = resource_sql.read_text(encoding="utf-8")
    assert "resource_measurements" in text and "resource_unit_prices" in text
    assert "quantity NUMERIC" in text and "unit_price NUMERIC" in text
    worker_status_sql = path.parents[2] / "worker_status" / "schema_postgres.sql"
    text = worker_status_sql.read_text(encoding="utf-8")
    assert "worker_heartbeats" in text and "TIMESTAMPTZ" in text
    assert "ix_worker_heartbeats_provider" in text
    conformance_job_sql = path.parents[2] / "provider_conformance" / "schema.sql"
    text = conformance_job_sql.read_text(encoding="utf-8")
    assert "provider_conformance_jobs" in text and "TIMESTAMPTZ" in text
    assert "REFERENCES provider_conformance_tests" in text
    assert "provider_conformance_jobs_one_active_idx" in text
    conformance_job_store = (
        path.parents[2] / "provider_conformance" / "store.py"
    ).read_text(encoding="utf-8")
    assert "FOR UPDATE SKIP LOCKED" in conformance_job_store
    campaign_sql = path.parents[2] / "comparison_campaign" / "schema.sql"
    text = campaign_sql.read_text(encoding="utf-8")
    assert "comparison_campaigns" in text and "comparison_campaign_entries" in text
    assert "comparison_campaign_finalizations" in text
    assert "WAITING','RUNNING','SUCCEEDED','FAILED" in text
    assert "REFERENCES comparison_reports(comparison_id)" in text
    assert "UNIQUE(requested_by, request_key_hash)" in text
    assert "REFERENCES forecast_runs(run_id)" in text
    campaign_store = (
        path.parents[2] / "comparison_campaign" / "store.py"
    ).read_text(encoding="utf-8")
    assert "FOR UPDATE SKIP LOCKED" in campaign_store


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_store_conforms_to_origin_transaction_contract():
    dsn = os.environ["KIBAN_TEST_POSTGRES_DSN"]
    store = PostgresRunStore(dsn)
    run_id = f"phase1d-{uuid.uuid4()}"
    store.create_run(
        RunDefinition(run_id, "experiment", "fingerprint", "builtin-baseline", "ma", 1),
        (origin(1),),
        (expectation(1),),
    )
    other_run_id = f"phase1d-other-{uuid.uuid4()}"
    store.create_run(
        RunDefinition(
            other_run_id,
            "experiment-other",
            "fingerprint-other",
            "other-provider",
            "other-model",
            1,
        ),
        (origin(1),),
        (expectation(1),),
    )
    assert (run_id, "fingerprint") in store.list_runnable_runs("builtin-baseline")
    assert (other_run_id, "fingerprint-other") not in store.list_runnable_runs(
        "builtin-baseline"
    )
    assert (other_run_id, "fingerprint-other") in store.list_runnable_runs(
        "other-provider"
    )
    store.start_or_resume(run_id, "fingerprint")
    lease = store.claim_next_origin(run_id, "worker", 60)
    assert lease is not None
    store.complete_origin(lease, OriginOutput((point(1),)))
    assert store.finish_run(run_id) == "SUCCEEDED"
    resource_cost = PostgresResourceCostStore(dsn)
    worker_status = PostgresWorkerStatusStore(dsn)
    worker_id = f"postgres-worker-{uuid.uuid4()}"
    worker_status.register(worker_id, str(uuid.uuid4()), "builtin-baseline")
    heartbeat = next(
        item for item in worker_status.list_workers() if item.worker_id == worker_id
    )
    assert heartbeat.state == WorkerState.IDLE
    resource_cost.record_attempt(
        run_id,
        date(2026, 1, 1),
        1,
        (ResourceUsage(ResourceMetric.CPU_SECONDS, Decimal("2"), "postgres-test"),),
    )
    resource_cost.put_unit_price(
        make_unit_price(
            provider_id="builtin-baseline",
            metric=ResourceMetric.CPU_SECONDS,
            unit_price=Decimal("3"),
            currency="JPY",
            retrieved_on=date(2026, 9, 16),
            source_ref="postgres contract test",
            created_by="test@example.test",
        )
    )
    assert resource_cost.summarize(run_id)["total_cost_amount"] == "6"
    catalog = PostgresCatalogStore(dsn)
    snapshot = make_snapshot(snapshot_payload())
    catalog.put_snapshot(snapshot)
    assert catalog.get_snapshot(snapshot.snapshot_id) == snapshot
    experiment = make_experiment(
        snapshot,
        {
            "snapshot_id": snapshot.snapshot_id,
            "provider_id": "builtin-baseline",
            "model_name": "moving_average_28",
            "params": {},
            "interval_levels": [],
            "preprocessing_version": "daily-v1",
            "seed": 7,
            "resource_profile": f"postgres-{uuid.uuid4()}",
            "training_policy": "FIXED",
        },
    )
    catalog.put_experiment(experiment)
    ingestion = PostgresIngestionStore(dsn)
    job = ingestion.enqueue(f"phase1g-{uuid.uuid4()}.csv")
    assert ingestion.claim().import_id == job.import_id
    ingestion.finish(job.import_id)
    assert ingestion.get_job(job.import_id).status == "SUCCEEDED"
    source_file = SourceFile(
        str(uuid.uuid4()),
        job.import_id,
        job.source_path,
        42,
        uuid.uuid4().hex * 2,
        "utf-8",
        "ACCEPTED",
        f"/tmp/{job.source_path}",
    )
    ingestion.record_file(source_file)
    assert any(value.import_id == job.import_id for value in ingestion.list_jobs())
    normalization = PostgresNormalizationStore(dsn)
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
    assert mapping in normalization.list_mappings()
    normalization_job = normalization.enqueue(source_file.source_file_id, mapping.mapping_id)
    row = ShipmentRow(
        normalization_job.normalization_id,
        source_file.source_file_id,
        2,
        "C1",
        "2026-02-01",
        f"jan-{uuid.uuid4().hex}",
        "PostgreSQL商品",
        Decimal("2"),
        "PACK",
        "SHIPMENT",
        "2026-02-02T00:00:00+09:00",
        "ACCEPTED",
        None,
    )
    reconciliation = Reconciliation(
        normalization_job.normalization_id,
        Decimal("2"),
        Decimal("2"),
        Decimal("0"),
        Decimal("0"),
    )
    normalization.complete(normalization_job.normalization_id, [row], reconciliation)
    assert any(
        value.normalization_id == normalization_job.normalization_id
        for value in normalization.list_jobs()
    )
    assert normalization.summary(normalization_job.normalization_id)["reconciliation"][
        "accepted_quantity"
    ] == "2"
    total, page = normalization.list_rows_page(
        normalization_job.normalization_id, status="ACCEPTED", limit=1
    )
    assert total == 1 and page[0]["raw_jan"] == row.raw_jan
    master = PostgresMasterStore(dsn)
    matching_job = make_matching_job(
        {
            "normalization_ids": [normalization_job.normalization_id],
            "policy_version": "postgres-list-v1",
            "similarity_threshold": 0.85,
            "handoff_similarity_threshold": 0.6,
            "max_handoff_gap_days": 31,
        }
    )
    master.put_job(matching_job)
    assert any(
        value.matching_job_id == matching_job.matching_job_id for value in master.list_jobs()
    )
    product = make_product(
        f"PostgreSQL確認-{uuid.uuid4()}", "test@example.test", "live store適合確認"
    )
    master.put_product(product)
    assert any(
        value["canonical_product_id"] == product.canonical_product_id
        for value in master.list_products()
    )
    evaluation = PostgresEvaluationRegistryStore(dsn)
    metadata = registry.create("builtin-baseline").metadata()
    conformance = make_conformance(
        {
            "provider_id": metadata.provider_id,
            "provider_version": metadata.provider_version,
            "model_id": "moving_average_28",
            "library_name": metadata.library_name,
            "library_version": metadata.library_version,
            "test_suite_version": "postgres-contract-v1",
            "adapter_config": {},
            "environment": {
                "python_version": "3.13.7",
                "platform": "postgres-test",
                "dependencies": {metadata.library_name: metadata.library_version},
                "container_digest": None,
            },
            "checks": [
                {"code": code, "status": "PASSED", "evidence": f"test:{code}"}
                for code in sorted(REQUIRED_CHECKS)
            ],
            "executed_by": "test@example.test",
            "executed_at": datetime.now(UTC).isoformat(),
            "evidence_uri": None,
            "evidence_sha256": None,
        },
        metadata,
    )
    evaluation.put_conformance(conformance)
    conformance_jobs = PostgresConformanceJobStore(dsn)
    conformance_provider = f"postgres-conformance-{uuid.uuid4()}"
    conformance_job = conformance_jobs.enqueue(
        experiment.experiment_id,
        conformance_provider,
        "moving_average_28",
        "test@example.test",
    )
    claimed = conformance_jobs.claim(conformance_provider)
    assert claimed is not None and claimed.job_id == conformance_job.job_id
    conformance_jobs.fail(claimed.job_id, "POSTGRES_TEST", "expected test failure")
    assert conformance_jobs.get_job(claimed.job_id).status == "FAILED"
    campaigns = PostgresComparisonCampaignStore(dsn)
    request_key = f"postgres-campaign-{uuid.uuid4()}"
    campaign, created = campaigns.reserve(
        request_key,
        snapshot.snapshot_id,
        "test@example.test",
        "PostgreSQL比較キャンペーン確認",
        '["builtin-baseline/moving_average_28"]',
    )
    assert created is True
    same, created = campaigns.reserve(
        request_key,
        snapshot.snapshot_id,
        "test@example.test",
        "PostgreSQL比較キャンペーン確認",
        '["builtin-baseline/moving_average_28"]',
    )
    assert created is False and same == campaign
    campaign_entry = CampaignEntry(
        campaign.campaign_id,
        "builtin-baseline",
        "moving_average_28",
        experiment.experiment_id,
        conformance_job.job_id,
        run_id,
    )
    assert campaigns.put_entry(campaign_entry) == campaign_entry
    assert campaigns.list_entries(campaign.campaign_id) == [campaign_entry]
    comparison = make_comparison_record(
        {
            "truth_version": "postgres-truth-v1",
            "evaluation_scope_hash": "postgres-scope-v1",
            "mode": "horizon",
            "horizon": 1,
            "nonce": str(uuid.uuid4()),
        },
        {
            "comparison_set_id": "reference-set",
            "official_comparison_set_id": "official-set",
            "ranking_ready": True,
            "official_ranking_ready": False,
        },
    )
    score = RunEvaluation(
        comparison.comparison_id,
        run_id,
        "builtin-baseline",
        "moving_average_28",
        conformance.conformance_id,
        {"own_metrics": {"mae": 0.0}},
    )
    saved = evaluation.put_comparison(comparison, [score])
    assert evaluation.get_comparison(saved.comparison_id) == saved
    assert evaluation.list_run_evaluations(saved.comparison_id) == [score]
    PostgresAcceptanceStore(dsn)
    PostgresModelReviewStore(dsn)
    reporting = PostgresReportingStore(dsn)
    export = make_export_record(
        {
            "comparison_id": saved.comparison_id,
            "export_version": f"postgres-export-{uuid.uuid4()}",
            "baseline_run_id": run_id,
            "requested_by": "test@example.test",
        },
        "file:///tmp/postgres-report.csv",
        "c" * 64,
        1,
    )
    assert reporting.put_export(export) == export
    assert reporting.get_export(export.export_id) == export
    adoption = make_adoption(
        {
            "adoption_version": f"postgres-adoption-{uuid.uuid4()}",
            "comparison_id": saved.comparison_id,
            "acceptance_case_id": None,
            "decision": "REJECTED",
            "selected_run_id": None,
            "fallback_run_id": None,
            "target": {
                "selection_version": "selection-v1",
                "canonical_product_ids": ["P1"],
                "center_ids": ["C1"],
                "trial_period_days": 30,
            },
            "decided_by": "test@example.test",
            "reason": "PostgreSQL保存確認",
        }
    )
    assert reporting.put_adoption(adoption) == adoption
    assert reporting.get_adoption(adoption.adoption_id) == adoption
