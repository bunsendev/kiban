"""保存済みrunから比較を再構成する評価レジストリサービス。"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from ..catalog import CatalogStore
from ..catalog.domain import dataset_from_snapshot
from ..catalog.files import verify_snapshot_file
from ..contracts import PREDICT_REQUIRED_COLUMNS
from ..errors import ProviderError
from ..evaluation import compare_runs
from ..jobs.contracts import RunStore
from ..registry import registry
from ..resource_cost.contracts import ResourceCostStore
from .contracts import (
    ComparisonRecord,
    EvaluationRegistryStore,
    ProviderConformance,
    RunEvaluation,
)
from .domain import digest, make_comparison_record, make_conformance

TERMINAL_STATUSES = frozenset({"SUCCEEDED", "PARTIAL", "FAILED"})


class EvaluationNotFound(KeyError):
    pass


class EvaluationConflict(ValueError):
    pass


class EvaluationRegistryService:
    def __init__(
        self,
        runs: RunStore,
        catalog: CatalogStore,
        store: EvaluationRegistryStore,
        snapshot_root: Path | None = None,
        resource_cost: ResourceCostStore | None = None,
    ) -> None:
        self.runs = runs
        self.catalog = catalog
        self.store = store
        self.snapshot_root = snapshot_root
        self.resource_cost = resource_cost

    def create_conformance(self, definition: dict) -> ProviderConformance:
        try:
            metadata = registry.create(definition["provider_id"]).metadata()
        except (KeyError, ProviderError) as exc:
            raise ValueError("未登録providerです") from exc
        return self.store.put_conformance(make_conformance(definition, metadata))

    def get_conformance(self, conformance_id: str) -> ProviderConformance:
        value = self.store.get_conformance(conformance_id)
        if value is None:
            raise EvaluationNotFound(conformance_id)
        return value

    def list_conformance(
        self, provider_id: str | None = None, model_id: str | None = None
    ) -> list[ProviderConformance]:
        return self.store.list_conformance(provider_id, model_id)

    def list_providers(self) -> list[dict]:
        providers = []
        for metadata in registry.list_metadata():
            value = asdict(metadata)
            records = [
                record
                for record in self.store.list_conformance(metadata.provider_id)
                if record.provider_version == metadata.provider_version
                and record.library_name == metadata.library_name
                and record.library_version == metadata.library_version
            ]
            latest = {
                model.model_id: next(
                    (record for record in records if record.model_id == model.model_id), None
                )
                for model in metadata.models
            }
            value["models"] = [
                {
                    **asdict(model),
                    "latest_conformance": (
                        None if latest[model.model_id] is None else asdict(latest[model.model_id])
                    ),
                    "fixed_ranking_eligible": bool(
                        latest[model.model_id]
                        and latest[model.model_id].fixed_ranking_eligible
                    ),
                }
                for model in metadata.models
            ]
            providers.append(value)
        return providers

    def create_comparison(self, request: dict) -> ComparisonRecord:
        run_ids = request["run_ids"]
        conformance_ids = request["conformance_ids"]
        datasets, outputs, run_details = {}, {}, {}
        eligible = set()
        truth_snapshot = None
        for run_id in run_ids:
            run = self.runs.get_run(run_id)
            if run is None:
                raise EvaluationNotFound(run_id)
            if run.status not in TERMINAL_STATUSES:
                raise EvaluationConflict("終端状態のrunだけを比較できます")
            experiment = self.catalog.get_experiment(run.experiment_id)
            if experiment is None:
                raise EvaluationNotFound(run.experiment_id)
            snapshot = self.catalog.get_snapshot(experiment.snapshot_id)
            if snapshot is None:
                raise EvaluationNotFound(experiment.snapshot_id)
            if snapshot.snapshot_id != request["truth_snapshot_id"]:
                raise EvaluationConflict("runとtruth snapshotが一致しません")
            truth_snapshot = snapshot
            definition = experiment.definition
            conformance = self.get_conformance(conformance_ids[run_id])
            expected_config = {
                "params": definition.get("params", {}),
                "interval_levels": definition.get("interval_levels", []),
                "preprocessing_version": definition["preprocessing_version"],
            }
            if (
                conformance.provider_id != definition["provider_id"]
                or conformance.model_id != definition["model_name"]
                or conformance.adapter_config != expected_config
            ):
                raise EvaluationConflict("runとProvider適合記録の条件が一致しません")
            result = self.runs.get_run_results(run_id)
            if result is None:
                raise EvaluationNotFound(run_id)
            datasets[run_id] = dataset_from_snapshot(snapshot)
            outputs[run_id] = _prediction_frame(result["values"])
            run_details[run_id] = (definition["provider_id"], definition["model_name"])
            # 月次再学習は仕様上reference比較であり、固定学習の正式順位へ混ぜない。
            if (
                conformance.fixed_ranking_eligible
                and definition.get("training_policy", "FIXED") == "FIXED"
            ):
                eligible.add(run_id)
        if truth_snapshot is None:
            raise ValueError("run_idsは1件以上必要です")
        truth = _truth_frame(truth_snapshot.manifest, self.snapshot_root)
        report = compare_runs(
            datasets,
            outputs,
            truth,
            truth_version=truth_snapshot.content_hash,
            mode=request["mode"],
            horizon=request["horizon"],
            official_eligible_runs=eligible,
        )
        scope_hash = digest(_scope_value(next(iter(datasets.values())).evaluation_scope))
        definition = {
            "run_ids": sorted(run_ids),
            "conformance_ids": dict(sorted(conformance_ids.items())),
            "truth_snapshot_id": truth_snapshot.snapshot_id,
            "truth_version": truth_snapshot.content_hash,
            "evaluation_scope_hash": scope_hash,
            "mode": request["mode"],
            "horizon": request["horizon"],
            "policy_version": request["policy_version"],
            "requested_by": request["requested_by"],
            "purpose": request["purpose"],
        }
        record = make_comparison_record(definition, report)
        evaluations = [
            RunEvaluation(
                record.comparison_id,
                run_id,
                run_details[run_id][0],
                run_details[run_id][1],
                conformance_ids[run_id],
                report["scores"][run_id],
            )
            for run_id in sorted(run_ids)
        ]
        return self.store.put_comparison(record, evaluations)

    def get_comparison(self, comparison_id: str) -> ComparisonRecord:
        value = self.store.get_comparison(comparison_id)
        if value is None:
            raise EvaluationNotFound(comparison_id)
        return value

    def list_comparisons(self, run_id: str | None = None) -> list[ComparisonRecord]:
        return self.store.list_comparisons(run_id)

    def comparison_detail(self, comparison_id: str) -> dict:
        record = self.get_comparison(comparison_id)
        evaluations = self.store.list_run_evaluations(comparison_id)
        return {
            **asdict(record),
            "run_evaluations": [
                {
                    **asdict(value),
                    "resources": (
                        None
                        if self.resource_cost is None
                        else self.resource_cost.summarize(value.run_id)
                    ),
                }
                for value in evaluations
            ],
        }


def _truth_frame(manifest: dict, root: Path | None) -> pd.DataFrame:
    path = verify_snapshot_file(manifest["data_uri"], manifest["data_sha256"], root)
    frame = pd.read_csv(path, parse_dates=["ds"])
    if "daily_state" in frame:
        excluded = {"MISSING", "NOT_HANDLED", "CLOSED", "PARTIAL_OR_INVALID"}
        frame.loc[frame["daily_state"].isin(excluded), "y"] = float("nan")
    return frame[["unique_id", "ds", "y"]]


def _prediction_frame(values: list[dict]) -> pd.DataFrame:
    if not values:
        return pd.DataFrame(columns=PREDICT_REQUIRED_COLUMNS)
    frame = pd.DataFrame(values)[list(PREDICT_REQUIRED_COLUMNS)].copy()
    for name in ("origin_date", "target_date"):
        frame[name] = pd.to_datetime(frame[name])
    frame["horizon"] = frame["horizon"].astype(int)
    frame["quantile"] = pd.to_numeric(frame["quantile"], errors="coerce")
    for name in ("yhat_raw", "yhat"):
        frame[name] = pd.to_numeric(frame[name])
    return frame


def _scope_value(scope: tuple[object, ...]) -> list:
    return [
        [str(item) for item in value] if isinstance(value, tuple) else str(value)
        for value in scope
    ]
