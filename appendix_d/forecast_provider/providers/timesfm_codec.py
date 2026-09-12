"""TimesFM 2.5の参照情報だけを保存する版付きJSON artifact契約。"""

from __future__ import annotations

import re
from dataclasses import replace

from ..artifacts import json_format as jf
from ..artifacts.contracts import ArtifactError
from .series_codec import decode_series_map, encode_series_map
from .timesfm_2p5 import MODEL_ID, TimesFM2p5Provider
from .timesfm_checkpoint import CHECKPOINT_SHA256, CHECKPOINT_SIZE, WEIGHTS_ID
from .timesfm_runtime import MODEL_PARAMS

MODEL_STATE_FIELDS = {
    "dataset_unique_ids",
    "dataset_max_horizon",
    "known_future_columns",
    "params",
    "interval_levels",
    "eligible_unique_ids",
    "excluded_unique_ids",
    "exclusion_reasons",
    "train_imputed_counts",
    "checkpoint_sha256",
    "checkpoint_size_bytes",
    "seed",
    "run_id",
    "experiment_id",
}
CONTEXT_STATE_FIELDS = {"series", "imputed_counts", "weights_id"}


class TimesFM2p5Codec:
    codec_version = 1

    def metadata(self):
        return TimesFM2p5Provider().metadata()

    def encode_model(self, model, dataset, config, context) -> dict:
        jf.keys(model.state, MODEL_STATE_FIELDS)
        state = model.state
        payload = {
            "dataset_unique_ids": list(state["dataset_unique_ids"]),
            "dataset_max_horizon": state["dataset_max_horizon"],
            "known_future_columns": list(state["known_future_columns"]),
            "params": dict(state["params"]),
            "interval_levels": list(state["interval_levels"]),
            "eligible_unique_ids": list(state["eligible_unique_ids"]),
            "excluded_unique_ids": list(state["excluded_unique_ids"]),
            "exclusion_reasons": dict(sorted(state["exclusion_reasons"].items())),
            "train_imputed_counts": dict(sorted(state["train_imputed_counts"].items())),
            "checkpoint_sha256": state["checkpoint_sha256"],
            "checkpoint_size_bytes": state["checkpoint_size_bytes"],
            "seed": state["seed"],
            "run_id": state["run_id"],
            "experiment_id": state["experiment_id"],
        }
        self.decode_model(payload, model, dataset, config, context)
        return payload

    def decode_model(self, payload, model, dataset, config, context):
        jf.keys(payload, MODEL_STATE_FIELDS)
        if model.weights_id != WEIGHTS_ID or model.model_name != MODEL_ID:
            raise ArtifactError("TimesFMのweights/model指定が不正です")
        if not TimesFM2p5Provider().validate(dataset, config).ok:
            raise ArtifactError("TimesFMの設定が非対応です")

        unique_ids = jf.unique_strings(payload["dataset_unique_ids"])
        known_future = jf.unique_strings(payload["known_future_columns"])
        eligible = jf.unique_strings(payload["eligible_unique_ids"])
        excluded = jf.unique_strings(payload["excluded_unique_ids"])
        max_horizon = jf.integer(payload["dataset_max_horizon"], minimum=1)
        seed = jf.integer(payload["seed"])
        run_id = jf.text(payload["run_id"])
        experiment_id = jf.text(payload["experiment_id"])
        checksum = jf.text(payload["checkpoint_sha256"])
        checkpoint_size = jf.integer(payload["checkpoint_size_bytes"], minimum=1)
        if payload["params"] != MODEL_PARAMS or payload["interval_levels"] != []:
            raise ArtifactError("TimesFM params/interval_levelsが不正です")
        if (
            set(unique_ids) != set(dataset.unique_ids)
            or set(known_future) != set(dataset.known_future_columns)
            or max_horizon != dataset.max_horizon
            or seed != context.seed
            or run_id != context.run_id
            or experiment_id != context.experiment_id
        ):
            raise ArtifactError("TimesFM stateと学習条件が一致しません")
        if (
            checksum != CHECKPOINT_SHA256
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
            or checkpoint_size != CHECKPOINT_SIZE
        ):
            raise ArtifactError("TimesFM checkpoint識別が不正です")

        reasons = _text_map(payload["exclusion_reasons"], "exclusion_reasons")
        imputed = _count_map(payload["train_imputed_counts"], "train_imputed_counts")
        eligible_ids = set(eligible)
        excluded_ids = set(excluded)
        if (
            not eligible_ids
            or eligible_ids & excluded_ids
            or eligible_ids | excluded_ids != set(unique_ids)
            or set(imputed) != eligible_ids
            or set(reasons) != excluded_ids
        ):
            raise ArtifactError("TimesFM対象/除外系列の不一致")
        return replace(
            model,
            state={
                "dataset_unique_ids": unique_ids,
                "dataset_max_horizon": max_horizon,
                "known_future_columns": known_future,
                "params": dict(MODEL_PARAMS),
                "interval_levels": (),
                "eligible_unique_ids": eligible,
                "excluded_unique_ids": excluded,
                "exclusion_reasons": reasons,
                "train_imputed_counts": imputed,
                "checkpoint_sha256": checksum,
                "checkpoint_size_bytes": checkpoint_size,
                "seed": seed,
                "run_id": run_id,
                "experiment_id": experiment_id,
            },
        )

    def encode_context(self, ref, model) -> dict:
        jf.keys(ref.state, CONTEXT_STATE_FIELDS)
        payload = {
            "series": encode_series_map(ref.state["series"]),
            "imputed_counts": dict(sorted(ref.state["imputed_counts"].items())),
            "weights_id": ref.state["weights_id"],
        }
        self.decode_context(payload, ref, model)
        return payload

    def decode_context(self, payload, ref, model):
        jf.keys(payload, CONTEXT_STATE_FIELDS)
        series = decode_series_map(payload["series"])
        imputed = _count_map(payload["imputed_counts"], "imputed_counts")
        weights_id = jf.text(payload["weights_id"])
        if (
            weights_id != WEIGHTS_ID
            or ref.origin_date < model.train_end_date
            or ref.history_end > ref.origin_date
            or not set(series).issubset(set(model.state["eligible_unique_ids"]))
            or set(imputed) != set(series)
        ):
            raise ArtifactError("TimesFM contextのモデル/日付/系列が不正です")
        for value in series.values():
            if (
                value.isna().any()
                or len(value) > MODEL_PARAMS["max_context"]
                or value.index[-1].date() > ref.origin_date
            ):
                raise ArtifactError("TimesFM context履歴が不正です")
        return replace(
            ref,
            state={
                "series": series,
                "imputed_counts": imputed,
                "weights_id": weights_id,
            },
        )


def _mapping(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ArtifactError(f"TimesFM {name}がobjectではありません")
    return {jf.text(key): item for key, item in value.items()}


def _text_map(value, name: str) -> dict[str, str]:
    return {key: jf.text(item) for key, item in _mapping(value, name).items()}


def _count_map(value, name: str) -> dict[str, int]:
    return {key: jf.integer(item, minimum=0) for key, item in _mapping(value, name).items()}
