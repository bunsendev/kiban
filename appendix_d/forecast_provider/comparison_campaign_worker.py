"""完了した比較キャンペーンから比較結果を自動生成する独立Worker。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .api.campaign_service import ComparisonCampaignService
from .api.service import ApplicationService
from .catalog import PostgresCatalogStore, SqliteCatalogStore
from .comparison_campaign import (
    PostgresComparisonCampaignStore,
    SqliteComparisonCampaignStore,
)
from .evaluation_registry import (
    PostgresEvaluationRegistryStore,
    SqliteEvaluationRegistryStore,
)
from .evaluation_registry.service import EvaluationRegistryService
from .jobs import PostgresRunStore, SqliteRunStore
from .operations.worker_config import add_database_arguments, postgres_dsn
from .provider_conformance import PostgresConformanceJobStore, SqliteConformanceJobStore
from .provider_conformance.service import ConformanceJobService


def work_once(campaigns, campaign_service, evaluation_service) -> int:
    finalization = campaigns.claim_finalization()
    if finalization is None:
        return 0
    try:
        detail = campaign_service.detail(finalization.campaign_id)
        if detail["status"] == "RUNNING":
            campaigns.defer_finalization(finalization.campaign_id)
            return 1
        if detail["status"] == "NEEDS_ATTENTION":
            raise ValueError("適合試験または予測runに失敗があります")
        conformance_ids = {
            entry["run_id"]: entry["conformance_id"] for entry in detail["entries"]
        }
        if not all(conformance_ids.values()):
            raise ValueError("比較に必要なProvider適合記録がありません")
        record = evaluation_service.create_comparison(
            {
                "run_ids": sorted(conformance_ids),
                "conformance_ids": conformance_ids,
                "truth_snapshot_id": detail["snapshot_id"],
                "mode": finalization.mode,
                "horizon": finalization.horizon,
                "policy_version": finalization.policy_version,
                "requested_by": detail["requested_by"],
                "purpose": detail["purpose"],
            }
        )
        campaigns.complete_finalization(finalization.campaign_id, record.comparison_id)
    except Exception as exc:
        campaigns.fail_finalization(
            finalization.campaign_id, type(exc).__name__, _safe_message(exc)
        )
    return 1


def _safe_message(exc: Exception) -> str:
    value = " ".join(str(exc).split())
    allowed = {
        "適合試験または予測runに失敗があります",
        "比較に必要なProvider適合記録がありません",
    }
    if value in allowed:
        return value
    return "比較結果を自動生成できませんでした。run、適合記録、snapshotを確認してください"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    add_database_arguments(parser)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)
    if args.poll_seconds <= 0:
        parser.error("--poll-secondsは正数です")
    if args.sqlite:
        runs = SqliteRunStore(args.sqlite)
        catalog = SqliteCatalogStore(args.sqlite)
        evaluations = SqliteEvaluationRegistryStore(args.sqlite)
        jobs = SqliteConformanceJobStore(args.sqlite)
        campaigns = SqliteComparisonCampaignStore(args.sqlite)
    else:
        dsn = postgres_dsn(args)
        runs = PostgresRunStore(dsn)
        catalog = PostgresCatalogStore(dsn)
        evaluations = PostgresEvaluationRegistryStore(dsn)
        jobs = PostgresConformanceJobStore(dsn)
        campaigns = PostgresComparisonCampaignStore(dsn)
    application = ApplicationService(runs, catalog, args.snapshot_root)
    conformance = ConformanceJobService(catalog, jobs)
    campaign_service = ComparisonCampaignService(campaigns, application, conformance)
    evaluation_service = EvaluationRegistryService(
        runs, catalog, evaluations, args.snapshot_root
    )
    while True:
        work_once(campaigns, campaign_service, evaluation_service)
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
