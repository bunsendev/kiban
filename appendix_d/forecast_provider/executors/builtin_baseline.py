"""保存済みexperiment/snapshotからbaseline起点を実行する。"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..artifacts import ArtifactRef, ForecastArtifactRepository, LocalArtifactStore
from ..catalog import CatalogStore
from ..catalog.domain import config_from_definition, dataset_from_snapshot
from ..catalog.files import verify_snapshot_file
from ..evaluation import build_plan
from ..features import attach_features
from ..jobs import ForecastValue, OriginOutput
from ..jobs.contracts import OriginLease, RunStore
from ..providers.baseline_codec import BuiltinBaselineCodec
from ..providers.builtin_baseline import BuiltinBaselineProvider
from ..run_context import RunContext
from ..runner import available_history


class BuiltinBaselineExecutor:
    def __init__(
        self, runs: RunStore, catalog: CatalogStore, artifact_root: Path, work_root: Path
    ) -> None:
        self.runs = runs
        self.catalog = catalog
        self.artifact_root = artifact_root
        self.work_root = work_root
        self._models: dict[str, tuple[object, ArtifactRef]] = {}

    def __call__(self, lease: OriginLease) -> OriginOutput:
        run = self.runs.get_run(lease.run_id)
        if run is None:
            raise KeyError(lease.run_id)
        experiment = self.catalog.get_experiment(run.experiment_id)
        if experiment is None:
            raise ValueError("runのexperimentが見つかりません")
        snapshot = self.catalog.get_snapshot(experiment.snapshot_id)
        if snapshot is None:
            raise ValueError("experimentのsnapshotが見つかりません")
        dataset = dataset_from_snapshot(snapshot)
        config = config_from_definition(experiment.definition)
        data, feature_versions = _read_snapshot(snapshot.manifest)
        context = _context(lease, run.experiment_id, experiment.definition, dataset, self.work_root)
        repository = ForecastArtifactRepository(
            LocalArtifactStore(self.artifact_root), [BuiltinBaselineCodec()]
        )
        provider = BuiltinBaselineProvider()
        model, model_artifact = self._model(
            lease.run_id,
            provider,
            repository,
            data,
            feature_versions,
            dataset,
            config,
            context,
        )
        origin = pd.Timestamp(lease.origin.origin_date)
        history = available_history(
            data,
            origin,
            availability_mode=dataset.availability_mode,
            known_future_columns=tuple(dataset.known_future_columns),
            feature_versions=feature_versions,
        )
        history = history[history.ds.ge(pd.Timestamp(dataset.train_start))]
        ref = provider.refresh_context(model, history, lease.origin.origin_date, context)
        context_artifact = repository.save_context(ref, model_artifact, dataset, config, context)
        restored = repository.load_context(
            context_artifact, model_artifact, dataset, config, context
        )
        targets = build_plan(dataset)
        targets = targets[targets.origin_date.eq(origin)]
        future = attach_features(
            targets, tuple(dataset.known_future_columns), versions=feature_versions
        )
        predicted = provider.predict(
            model, restored, future, sorted(targets.horizon.unique().tolist()), context
        )
        return OriginOutput(
            tuple(_value(row) for row in predicted.itertuples(index=False)),
            _artifact_text(model_artifact),
            _artifact_text(context_artifact),
        )

    def _model(
        self, run_id, provider, repository, data, feature_versions, dataset, config, context
    ):
        if run_id in self._models:
            return self._models[run_id]
        fit_context = context.for_origin(dataset.train_end)
        stored = self.runs.get_model_artifact(run_id)
        if stored:
            artifact = ArtifactRef.from_dict(json.loads(stored))
            model = repository.load_model(artifact, dataset, config, fit_context)
        else:
            train = available_history(
                data,
                pd.Timestamp(dataset.train_end),
                availability_mode=dataset.availability_mode,
                known_future_columns=tuple(dataset.known_future_columns),
                feature_versions=feature_versions,
            )
            train = train[train.ds.ge(pd.Timestamp(dataset.train_start))]
            fitted = provider.fit_parameters(train, dataset, config, fit_context)
            artifact = repository.save_model(fitted, dataset, config, fit_context)
            model = repository.load_model(artifact, dataset, config, fit_context)
        self._models[run_id] = (model, artifact)
        return model, artifact


def _context(lease, experiment_id, definition, dataset, work_root) -> RunContext:
    work = work_root / lease.run_id
    work.mkdir(parents=True, exist_ok=True)
    return RunContext(
        lease.run_id,
        experiment_id,
        int(definition["seed"]),
        lease.leased_until,
        work,
        work,
        definition["resource_profile"],
        logging.getLogger("baseline-worker"),
        availability_mode=dataset.availability_mode,
        cutoff_at=lease.origin.cutoff_at,
        origin_date=lease.origin.origin_date,
    )


def _read_snapshot(manifest: dict) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    path = verify_snapshot_file(manifest["data_uri"], manifest["data_sha256"])
    frame = pd.read_csv(path, parse_dates=["ds"])
    if "available_at" in frame:
        frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    feature_versions = None
    if manifest.get("feature_versions_uri"):
        feature_path = verify_snapshot_file(
            manifest["feature_versions_uri"], manifest["feature_versions_sha256"]
        )
        feature_versions = pd.read_csv(feature_path)
        feature_versions["ds"] = pd.to_datetime(feature_versions["ds"])
        feature_versions["known_at"] = pd.to_datetime(feature_versions["known_at"], utc=True)
    return frame, feature_versions


def _value(row) -> ForecastValue:
    quantile = None if pd.isna(row.quantile) else Decimal(str(row.quantile))
    return ForecastValue(
        row.unique_id,
        row.origin_date.date(),
        row.target_date.date(),
        int(row.horizon),
        row.forecast_kind,
        quantile,
        Decimal(str(row.yhat_raw)),
        Decimal(str(row.yhat)),
    )


def _artifact_text(ref: ArtifactRef) -> str:
    return json.dumps(ref.to_dict(), sort_keys=True, separators=(",", ":"))
