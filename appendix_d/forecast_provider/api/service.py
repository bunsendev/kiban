"""catalogとrun操作のアプリケーションサービス。HTTPへ依存しない。"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path

from ..catalog import CatalogStore, ExperimentRecord, SnapshotRecord
from ..catalog.domain import dataset_from_snapshot, make_experiment, make_snapshot
from ..catalog.files import verify_snapshot_file
from ..evaluation import build_plan
from ..jobs import Expectation, OriginDefinition, RunDefinition, RunSnapshot
from ..jobs.contracts import RunStore
from ..run_context import cutoff_for_origin
from .schemas import ExperimentCreate, RunCreate, SnapshotCreate


class NotFoundError(KeyError):
    pass


class ApplicationService:
    def __init__(
        self, runs: RunStore, catalog: CatalogStore, snapshot_root: Path | None = None
    ) -> None:
        self.runs = runs
        self.catalog = catalog
        self.snapshot_root = snapshot_root

    def create_snapshot(self, request: SnapshotCreate) -> SnapshotRecord:
        if self.snapshot_root is not None:
            verify_snapshot_file(request.data_uri, request.data_sha256, self.snapshot_root)
            if request.feature_versions_uri:
                verify_snapshot_file(
                    request.feature_versions_uri,
                    request.feature_versions_sha256,
                    self.snapshot_root,
                )
        record = make_snapshot(request.model_dump(mode="json"))
        self.catalog.put_snapshot(record)
        return record

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord:
        record = self.catalog.get_snapshot(snapshot_id)
        if record is None:
            raise NotFoundError(snapshot_id)
        return record

    def create_experiment(self, request: ExperimentCreate) -> ExperimentRecord:
        snapshot = self.get_snapshot(request.snapshot_id)
        record = make_experiment(snapshot, request.model_dump(mode="json"))
        self.catalog.put_experiment(record)
        return record

    def get_experiment(self, experiment_id: str) -> ExperimentRecord:
        record = self.catalog.get_experiment(experiment_id)
        if record is None:
            raise NotFoundError(experiment_id)
        return record

    def create_run(self, request: RunCreate) -> RunSnapshot:
        experiment = self.get_experiment(request.experiment_id)
        snapshot = self.get_snapshot(experiment.snapshot_id)
        dataset = dataset_from_snapshot(snapshot)
        plan = build_plan(dataset)
        origins = tuple(
            OriginDefinition(origin, cutoff_for_origin(origin)) for origin in dataset.origin_dates()
        )
        expectations = tuple(
            Expectation(
                row.unique_id,
                row.origin_date.date(),
                row.target_date.date(),
                int(row.horizon),
            )
            for row in plan.itertuples(index=False)
        )
        definition = experiment.definition
        run_id = str(uuid.uuid4())
        self.runs.create_run(
            RunDefinition(
                run_id,
                experiment.experiment_id,
                experiment.condition_fingerprint,
                definition["provider_id"],
                definition["model_name"],
                int(definition["seed"]),
            ),
            origins,
            expectations,
        )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> RunSnapshot:
        snapshot = self.runs.get_run(run_id)
        if snapshot is None:
            raise NotFoundError(run_id)
        return snapshot

    def get_results(self, run_id: str) -> dict:
        result = self.runs.get_run_results(run_id)
        if result is None:
            raise NotFoundError(run_id)
        return result

    def cancel(self, run_id: str) -> RunSnapshot:
        self.get_run(run_id)
        self.runs.request_cancellation(run_id)
        return self.get_run(run_id)

    def resume(self, run_id: str, fingerprint: str) -> RunSnapshot:
        self.get_run(run_id)
        self.runs.start_or_resume(run_id, fingerprint)
        return self.get_run(run_id)


def record_dict(record: SnapshotRecord | ExperimentRecord) -> dict:
    return asdict(record)
