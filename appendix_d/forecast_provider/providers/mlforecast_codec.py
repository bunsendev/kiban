"""MLForecast Ridgeの版付きJSON artifact契約。"""

from __future__ import annotations

import re
from dataclasses import replace

from ..artifacts import json_format as jf
from ..artifacts.contracts import ArtifactError
from .mlforecast_ridge import MODEL_ID, MLForecastRidgeProvider
from .mlforecast_state import MODEL_PARAMS, model_signature, validate_ridge_state
from .series_codec import decode_series_map, encode_series_map

MODEL_STATE_FIELDS = {
    "dataset_unique_ids",
    "dataset_max_horizon",
    "known_future_columns",
    "params",
    "interval_levels",
    "models",
    "parameter_signatures",
    "excluded_unique_ids",
    "exclusion_reasons",
    "train_imputed_counts",
    "seed",
    "run_id",
    "experiment_id",
}
CONTEXT_STATE_FIELDS = {"series", "imputed_counts", "parameter_signatures"}


class MLForecastRidgeCodec:
    codec_version = 1

    def metadata(self):
        return MLForecastRidgeProvider().metadata()

    def encode_model(self, model, dataset, config, context) -> dict:
        jf.keys(model.state, MODEL_STATE_FIELDS)
        state = model.state
        payload = {
            "dataset_unique_ids": list(state["dataset_unique_ids"]),
            "dataset_max_horizon": state["dataset_max_horizon"],
            "known_future_columns": list(state["known_future_columns"]),
            "params": dict(state["params"]),
            "interval_levels": list(state["interval_levels"]),
            "models": {
                uid: validate_ridge_state(fitted)
                for uid, fitted in sorted(state["models"].items())
            },
            "parameter_signatures": dict(sorted(state["parameter_signatures"].items())),
            "excluded_unique_ids": list(state["excluded_unique_ids"]),
            "exclusion_reasons": dict(sorted(state["exclusion_reasons"].items())),
            "train_imputed_counts": dict(sorted(state["train_imputed_counts"].items())),
            "seed": state["seed"],
            "run_id": state["run_id"],
            "experiment_id": state["experiment_id"],
        }
        self.decode_model(payload, model, dataset, config, context)
        return payload

    def decode_model(self, payload, model, dataset, config, context):
        jf.keys(payload, MODEL_STATE_FIELDS)
        if model.weights_id is not None or model.model_name != MODEL_ID:
            raise ArtifactError("MLForecastのweights/model指定が不正です")
        if not MLForecastRidgeProvider().validate(dataset, config).ok:
            raise ArtifactError("MLForecastの設定が非対応です")

        unique_ids = jf.unique_strings(payload["dataset_unique_ids"])
        known_future = jf.unique_strings(payload["known_future_columns"])
        excluded = jf.unique_strings(payload["excluded_unique_ids"])
        max_horizon = jf.integer(payload["dataset_max_horizon"], minimum=1)
        seed = jf.integer(payload["seed"])
        run_id = jf.text(payload["run_id"])
        experiment_id = jf.text(payload["experiment_id"])
        if payload["params"] != MODEL_PARAMS or payload["interval_levels"] != []:
            raise ArtifactError("MLForecast params/interval_levelsが不正です")
        if (
            set(unique_ids) != set(dataset.unique_ids)
            or set(known_future) != set(dataset.known_future_columns)
            or max_horizon != dataset.max_horizon
            or seed != context.seed
            or run_id != context.run_id
            or experiment_id != context.experiment_id
        ):
            raise ArtifactError("MLForecast stateと学習条件が一致しません")

        raw_models = _mapping(payload["models"], "models")
        models = {uid: validate_ridge_state(item) for uid, item in raw_models.items()}
        signatures = _signature_map(payload["parameter_signatures"])
        reasons = _text_map(payload["exclusion_reasons"], "exclusion_reasons")
        imputed = _count_map(payload["train_imputed_counts"], "train_imputed_counts")
        fitted_ids = set(models)
        excluded_ids = set(excluded)
        if (
            not fitted_ids
            or fitted_ids & excluded_ids
            or fitted_ids | excluded_ids != set(unique_ids)
            or set(signatures) != fitted_ids
            or set(imputed) != fitted_ids
            or set(reasons) != excluded_ids
        ):
            raise ArtifactError("MLForecast学習/除外系列の不一致")
        if any(model_signature(item) != signatures[uid] for uid, item in models.items()):
            raise ArtifactError("MLForecast学習済みパラメータ署名不一致")
        return replace(
            model,
            state={
                "dataset_unique_ids": unique_ids,
                "dataset_max_horizon": max_horizon,
                "known_future_columns": known_future,
                "params": dict(MODEL_PARAMS),
                "interval_levels": (),
                "models": models,
                "parameter_signatures": signatures,
                "excluded_unique_ids": excluded,
                "exclusion_reasons": reasons,
                "train_imputed_counts": imputed,
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
            "parameter_signatures": dict(sorted(ref.state["parameter_signatures"].items())),
        }
        self.decode_context(payload, ref, model)
        return payload

    def decode_context(self, payload, ref, model):
        jf.keys(payload, CONTEXT_STATE_FIELDS)
        series = decode_series_map(payload["series"])
        imputed = _count_map(payload["imputed_counts"], "imputed_counts")
        signatures = _signature_map(payload["parameter_signatures"])
        fitted = set(model.state["models"])
        if (
            ref.origin_date < model.train_end_date
            or ref.history_end > ref.origin_date
            or not set(series).issubset(fitted)
            or set(imputed) != set(series)
            or signatures != model.state["parameter_signatures"]
        ):
            raise ArtifactError("MLForecast contextのモデル/日付/系列が不正です")
        for value in series.values():
            if (
                value.isna().any()
                or value.index[0].date() < model.train_start_date
                or value.index[-1].date() > ref.origin_date
            ):
                raise ArtifactError("MLForecast context履歴が不正です")
        return replace(
            ref,
            state={
                "series": series,
                "imputed_counts": imputed,
                "parameter_signatures": signatures,
            },
        )


def _mapping(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ArtifactError(f"MLForecast {name}がobjectではありません")
    return {jf.text(key): item for key, item in value.items()}


def _signature_map(value) -> dict[str, str]:
    result = _mapping(value, "parameter_signatures")
    if any(
        not isinstance(signature, str)
        or re.fullmatch(r"[0-9a-f]{64}", signature) is None
        for signature in result.values()
    ):
        raise ArtifactError("MLForecast parameter signatureが不正です")
    return result


def _text_map(value, name: str) -> dict[str, str]:
    return {key: jf.text(item) for key, item in _mapping(value, name).items()}


def _count_map(value, name: str) -> dict[str, int]:
    return {key: jf.integer(item, minimum=0) for key, item in _mapping(value, name).items()}
