"""Provider適合試験jobを実行して評価台帳へ自動登録する独立Worker。"""

from __future__ import annotations

import argparse
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from .catalog import PostgresCatalogStore, SqliteCatalogStore
from .evaluation_registry import (
    PostgresEvaluationRegistryStore,
    SqliteEvaluationRegistryStore,
    make_conformance,
)
from .operations.worker_config import add_database_arguments, postgres_dsn
from .provider_conformance import PostgresConformanceJobStore, SqliteConformanceJobStore
from .provider_conformance.evidence import save_evidence
from .provider_conformance.suite import SUITE_VERSION, run_suite
from .registry import registry


def work_once(jobs, catalog, evaluations, provider_id: str, evidence_root: Path) -> int:
    job = jobs.claim(provider_id)
    if job is None:
        return 0
    try:
        experiment = catalog.get_experiment(job.experiment_id)
        if experiment is None:
            raise ValueError("実験条件が見つかりません")
        snapshot = catalog.get_snapshot(experiment.snapshot_id)
        if snapshot is None:
            raise ValueError("dataset snapshotが見つかりません")
        if experiment.definition["provider_id"] != provider_id:
            raise ValueError("jobとWorkerのprovider_idが一致しません")
        provider = registry.create(provider_id)
        metadata = provider.metadata()
        result = run_suite(
            provider,
            experiment.definition,
            snapshot.manifest["availability_mode"],
            evidence_root / "work" / job.job_id,
        )
        executed_at = datetime.now(UTC).isoformat()
        evidence = {
            **result.evidence,
            "job_id": job.job_id,
            "experiment_id": job.experiment_id,
            "executed_at": executed_at,
            "executed_by": job.requested_by,
        }
        evidence_uri, evidence_sha256 = save_evidence(evidence_root / "objects", evidence)
        definition = experiment.definition
        record = make_conformance(
            {
                "provider_id": metadata.provider_id,
                "provider_version": metadata.provider_version,
                "model_id": definition["model_name"],
                "library_name": metadata.library_name,
                "library_version": metadata.library_version,
                "test_suite_version": SUITE_VERSION,
                "adapter_config": {
                    "params": definition.get("params", {}),
                    "interval_levels": definition.get("interval_levels", []),
                    "preprocessing_version": definition["preprocessing_version"],
                },
                "environment": {
                    "python_version": platform.python_version(),
                    "platform": platform.platform(),
                    "dependencies": dict(metadata.runtime_dependencies)
                    or {metadata.library_name: metadata.library_version},
                    "container_digest": metadata.container_digest,
                },
                "checks": result.checks,
                "executed_by": job.requested_by,
                "executed_at": executed_at,
                "evidence_uri": evidence_uri,
                "evidence_sha256": evidence_sha256,
            },
            metadata,
        )
        stored = evaluations.put_conformance(record)
        jobs.complete(job.job_id, stored.conformance_id)
    except Exception as exc:
        jobs.fail(job.job_id, type(exc).__name__, _safe_message(exc))
    return 1


def _safe_message(exc: Exception) -> str:
    value = " ".join(str(exc).split())
    return value[:500] or "適合試験を完了できませんでした"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    add_database_arguments(parser)
    parser.add_argument("--provider-id", action="append", required=True)
    parser.add_argument("--evidence-root", type=Path, default=Path("conformance_output"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    if args.poll_seconds <= 0:
        parser.error("--poll-secondsは正数です")
    try:
        metadata = [registry.create(value).metadata() for value in args.provider_id]
    except Exception as exc:
        parser.error(f"利用できないproviderがあります: {type(exc).__name__}")
    if [item.provider_id for item in metadata] != args.provider_id:
        parser.error("Providerメタデータの識別子が一致しません")
    if args.sqlite:
        catalog = SqliteCatalogStore(args.sqlite)
        evaluations = SqliteEvaluationRegistryStore(args.sqlite)
        jobs = SqliteConformanceJobStore(args.sqlite)
    else:
        dsn = postgres_dsn(args)
        catalog = PostgresCatalogStore(dsn)
        evaluations = PostgresEvaluationRegistryStore(dsn)
        jobs = PostgresConformanceJobStore(dsn)
    while True:
        processed = sum(
            work_once(jobs, catalog, evaluations, provider_id, args.evidence_root)
            for provider_id in args.provider_id
        )
        if args.once:
            return 0
        if not processed:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
