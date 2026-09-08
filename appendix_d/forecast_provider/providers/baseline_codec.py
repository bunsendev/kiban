"""builtin-baselineのstate保存契約。予測・残差の計算は行わない。"""

from dataclasses import replace

from ..artifacts import json_format as jf
from ..artifacts.contracts import ArtifactError
from ..frames import quantiles_from_interval_levels
from .baseline_series import decode_series_map, encode_series_map
from .builtin_baseline import SUPPORTED_MODELS, BuiltinBaselineProvider

STATE_FIELDS = {
    "dataset_unique_ids",
    "dataset_max_horizon",
    "known_future_columns",
    "train_series",
    "residual_quantiles",
    "interval_levels",
    "excluded_unique_ids",
    "seed",
    "run_id",
    "experiment_id",
}


def _encode_residuals(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ArtifactError("baseline残差集合が不正です")
    result = {}
    for uid, cache in value.items():
        jf.text(uid)
        if not isinstance(cache, dict):
            raise ArtifactError("baseline残差cacheが不正です")
        rows = []
        for key, correction in cache.items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise ArtifactError("baseline残差キーが不正です")
            rows.append([jf.integer(key[0], minimum=1), jf.number(key[1]), jf.number(correction)])
        result[uid] = sorted(rows)
    return result


def _decode_residuals(value: dict, max_horizon: int, quantiles: set) -> dict:
    if not isinstance(value, dict):
        raise ArtifactError("baseline残差集合が不正です")
    result = {}
    for uid, rows in value.items():
        jf.text(uid)
        if not isinstance(rows, list):
            raise ArtifactError("baseline残差配列が不正です")
        cache = {}
        for row in rows:
            if not isinstance(row, list) or len(row) != 3:
                raise ArtifactError("baseline残差行が不正です")
            h, q, correction = jf.integer(row[0], minimum=1), jf.number(row[1]), jf.number(row[2])
            if h > max_horizon or q not in quantiles or (h, q) in cache:
                raise ArtifactError("baseline残差horizon/quantile/重複が不正です")
            cache[h, q] = correction
        for horizon in {h for h, _ in cache}:
            if {q for h, q in cache if h == horizon} != quantiles:
                raise ArtifactError("baseline残差quantileの部分欠落")
        result[uid] = cache
    return result


class BuiltinBaselineCodec:
    codec_version = 1

    def metadata(self):
        return BuiltinBaselineProvider().metadata()

    def encode_model(self, model, dataset, config, context) -> dict:
        jf.keys(model.state, STATE_FIELDS)
        state = model.state
        payload = {
            name: state[name] for name in ("dataset_max_horizon", "seed", "run_id", "experiment_id")
        }
        for name in (
            "dataset_unique_ids",
            "known_future_columns",
            "interval_levels",
            "excluded_unique_ids",
        ):
            if not isinstance(state[name], (tuple, list)):
                raise ArtifactError("baseline state配列が不正です")
            payload[name] = list(state[name])
        payload["train_series"] = encode_series_map(state["train_series"])
        payload["residual_quantiles"] = _encode_residuals(state["residual_quantiles"])
        self.decode_model(payload, model, dataset, config, context)
        return payload

    def decode_model(self, payload, model, dataset, config, context):
        jf.keys(payload, STATE_FIELDS)
        if model.weights_id is not None or model.model_name not in SUPPORTED_MODELS:
            raise ArtifactError("baselineの重み/model指定が不正です")
        validation = BuiltinBaselineProvider().validate(dataset, config)
        if not validation.ok:
            raise ArtifactError("baselineの設定が非対応です")
        state = {
            "dataset_unique_ids": jf.unique_strings(payload["dataset_unique_ids"]),
            "known_future_columns": jf.unique_strings(payload["known_future_columns"]),
            "excluded_unique_ids": jf.unique_strings(payload["excluded_unique_ids"]),
            "dataset_max_horizon": jf.integer(payload["dataset_max_horizon"], minimum=1),
            "seed": jf.integer(payload["seed"]),
            "run_id": jf.text(payload["run_id"]),
            "experiment_id": jf.text(payload["experiment_id"]),
        }
        if not isinstance(payload["interval_levels"], list):
            raise ArtifactError("baseline interval_levels配列が不正です")
        state["interval_levels"] = tuple(jf.number(x) for x in payload["interval_levels"])
        if (
            set(state["dataset_unique_ids"]) != set(dataset.unique_ids)
            or set(state["known_future_columns"]) != set(dataset.known_future_columns)
            or state["dataset_max_horizon"] != dataset.max_horizon
            or sorted(state["interval_levels"]) != sorted(config.interval_levels)
            or state["seed"] != context.seed
            or state["run_id"] != context.run_id
            or state["experiment_id"] != context.experiment_id
        ):
            raise ArtifactError("baseline stateと期待する学習条件の不一致")
        state["train_series"] = decode_series_map(payload["train_series"])
        state["residual_quantiles"] = _decode_residuals(
            payload["residual_quantiles"],
            dataset.max_horizon,
            set(quantiles_from_interval_levels(config.interval_levels)),
        )
        fitted, excluded = set(state["train_series"]), set(state["excluded_unique_ids"])
        if (
            not fitted
            or fitted & excluded
            or fitted | excluded != set(dataset.unique_ids)
            or set(state["residual_quantiles"]) != fitted
        ):
            raise ArtifactError("baseline学習/除外系列の不一致")
        for series in state["train_series"].values():
            if (
                series.index[0].date() < model.train_start_date
                or series.index[-1].date() > model.train_end_date
                or series.notna().sum() < SUPPORTED_MODELS[model.model_name].min_history_days
            ):
                raise ArtifactError("baseline TRAIN範囲/有効履歴が不正です")
        return replace(model, state=state)

    def encode_context(self, ref, model) -> dict:
        jf.keys(ref.state, {"series"})
        payload = {"series": encode_series_map(ref.state["series"])}
        self.decode_context(payload, ref, model)
        return payload

    def decode_context(self, payload, ref, model):
        jf.keys(payload, {"series"})
        series = decode_series_map(payload["series"])
        if ref.origin_date < model.train_end_date or ref.history_end > ref.origin_date:
            raise ArtifactError("baseline contextの日付範囲不一致")
        if not set(series).issubset(model.state["train_series"]):
            raise ArtifactError("baseline contextに学習対象外の系列")
        if any(s.index[-1].date() > ref.history_end for s in series.values()):
            raise ArtifactError("baseline contextの履歴がhistory_endを超えています")
        return replace(ref, state={"series": series})
