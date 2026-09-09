"""manifest・experimentのcanonical化と実行契約への変換。"""

import hashlib
import json
from dataclasses import asdict
from datetime import date

from ..contracts import ForecastDataset, ProviderConfig
from ..errors import ProviderError
from ..registry import registry
from .contracts import ExperimentRecord, SnapshotRecord

FORMAT_VERSION = 1


def canonical(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode()


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def make_snapshot(manifest: dict) -> SnapshotRecord:
    dataset = dataset_from_manifest({**manifest, "dataset_snapshot_id": "pending"})
    normalized = asdict(dataset)
    normalized.pop("dataset_snapshot_id")
    normalized["data_uri"] = manifest["data_uri"]
    normalized["data_sha256"] = manifest["data_sha256"]
    normalized["feature_versions_uri"] = manifest.get("feature_versions_uri")
    normalized["feature_versions_sha256"] = manifest.get("feature_versions_sha256")
    if "provenance" in manifest:
        if not isinstance(manifest["provenance"], dict):
            raise ValueError("provenanceはobjectです")
        normalized["provenance"] = manifest["provenance"]
    normalized = json.loads(canonical(normalized))
    identifier = digest(normalized)
    return SnapshotRecord(identifier, FORMAT_VERSION, identifier, normalized)


def make_experiment(snapshot: SnapshotRecord, definition: dict) -> ExperimentRecord:
    config = config_from_definition(definition)
    try:
        validation = registry.create(config.provider_id).validate(
            dataset_from_snapshot(snapshot), config
        )
    except ProviderError as exc:
        raise ValueError("未登録providerです") from exc
    if not validation.ok:
        raise ValueError(str(validation.issues))
    normalized = {**definition, "snapshot_id": snapshot.snapshot_id}
    fingerprint = digest(normalized)
    return ExperimentRecord(
        fingerprint, FORMAT_VERSION, fingerprint, snapshot.snapshot_id, normalized
    )


def dataset_from_snapshot(snapshot: SnapshotRecord) -> ForecastDataset:
    return dataset_from_manifest({**snapshot.manifest, "dataset_snapshot_id": snapshot.snapshot_id})


def dataset_from_manifest(value: dict) -> ForecastDataset:
    fields = {
        key: value[key]
        for key in (
            "dataset_snapshot_id",
            "selection_version",
            "unique_ids",
            "train_start",
            "train_end",
            "test_start",
            "test_end",
            "origin_interval_days",
            "max_horizon",
            "primary_horizon_max",
            "report_horizons",
            "known_future_columns",
            "availability_mode",
        )
    }
    for name in ("train_start", "train_end", "test_start", "test_end"):
        if isinstance(fields[name], str):
            fields[name] = date.fromisoformat(fields[name])
    return ForecastDataset(**fields)


def config_from_definition(value: dict) -> ProviderConfig:
    return ProviderConfig(
        value["provider_id"],
        value["model_name"],
        value.get("params", {}),
        tuple(value.get("interval_levels", ())),
        preprocessing_version=value["preprocessing_version"],
    )
