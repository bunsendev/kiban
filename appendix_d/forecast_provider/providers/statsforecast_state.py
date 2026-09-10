"""AutoETSの因果的前処理と安全なJSON状態変換。"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from numbers import Integral, Real
from typing import Any

import numpy as np
import pandas as pd

from ..artifacts.contracts import ArtifactError

PREPROCESSING_VERSION = "statsforecast-causal-ffill-v1"
MODEL_PARAMS = {"season_length": 7, "model": "ZZZ"}
MODEL_PAYLOAD_FIELDS = {"m", "components", "par", "n_params", "fit"}
FIT_FIELDS = {"x", "fn", "nit", "simplex"}


def prepare_daily_series(
    group: pd.DataFrame, start: date, end: date
) -> tuple[pd.Series, int, int]:
    """指定期間を日次化し、過去方向だけから補完する。先頭欠損は除く。"""
    index = pd.date_range(start, end, freq="D")
    source = group.set_index("ds")["y"].astype("float64").reindex(index)
    actual_count = int(source.notna().sum())
    filled = source.ffill().dropna().astype("float64")
    filled.name = "y"
    filled.index.name = "ds"
    imputed_count = int(len(filled) - source.loc[filled.index].notna().sum())
    return filled, actual_count, imputed_count


def fit_auto_ets(series: pd.Series, params: dict[str, Any]):
    """依存を任意化するため、StatsForecastは実行時だけimportする。"""
    from statsforecast.models import AutoETS

    return AutoETS(**params).fit(series.to_numpy(dtype="float64"))


def forward_auto_ets(model, series: pd.Series, horizon: int) -> np.ndarray:
    values = model.forward(series.to_numpy(dtype="float64"), h=horizon)["mean"]
    result = np.asarray(values, dtype="float64")
    if result.shape != (horizon,) or not np.isfinite(result).all():
        raise ValueError("AutoETSが有限なhorizon一括予測を返しませんでした")
    return result


def encode_fitted_model(model) -> dict[str, Any]:
    """pickleを使わず、forwardに必要な学習済み状態だけをJSON木へ変換する。"""
    try:
        fitted = model.model_
        payload = {
            "m": _integer(fitted["m"], minimum=1),
            "components": _components(fitted["components"]),
            "par": _array(fitted["par"], allow_nan=True),
            "n_params": _integer(fitted["n_params"], minimum=1),
            "fit": {
                "x": _array(fitted["fit"].x, allow_nan=False),
                "fn": _number(fitted["fit"].fn),
                "nit": _integer(fitted["fit"].nit, minimum=0),
                "simplex": _array(fitted["fit"].simplex, allow_nan=False),
            },
        }
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        raise ArtifactError("AutoETS学習済み状態が不正です") from exc
    validate_model_payload(payload)
    return payload


def decode_fitted_model(payload: dict[str, Any]):
    checked = validate_model_payload(payload)
    from statsforecast.models import AutoETS
    from statsforecast.utils import results

    model = AutoETS(**MODEL_PARAMS)
    fit = checked["fit"]
    model.model_ = {
        "m": checked["m"],
        "components": checked["components"],
        "par": np.asarray(checked["par"], dtype="float64"),
        "n_params": checked["n_params"],
        "fit": results(
            x=np.asarray(fit["x"], dtype="float64"),
            fn=fit["fn"],
            nit=fit["nit"],
            simplex=np.asarray(fit["simplex"], dtype="float64"),
        ),
    }
    return model


def validate_model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != MODEL_PAYLOAD_FIELDS:
        raise ArtifactError("AutoETS modelフィールド不一致")
    if not isinstance(payload["fit"], dict) or set(payload["fit"]) != FIT_FIELDS:
        raise ArtifactError("AutoETS fitフィールド不一致")
    m = _integer(payload["m"], minimum=1)
    components = _components(payload["components"])
    par = _decoded_array(payload["par"], allow_nan=True, dimensions=1)
    n_params = _integer(payload["n_params"], minimum=1)
    fit = payload["fit"]
    x = _decoded_array(fit["x"], allow_nan=False, dimensions=1)
    simplex = _decoded_array(fit["simplex"], allow_nan=False, dimensions=2)
    # StatsForecastは一定値系列を非季節モデルへ縮約し、その場合mを1で保存する。
    if m not in (1, MODEL_PARAMS["season_length"]) or len(par) < 5 or n_params > len(par):
        raise ArtifactError("AutoETS周期/parameter数が不正です")
    return {
        "m": m,
        "components": components,
        "par": par,
        "n_params": n_params,
        "fit": {
            "x": x,
            "fn": _number(fit["fn"]),
            "nit": _integer(fit["nit"], minimum=0),
            "simplex": simplex,
        },
    }


def model_signature(model_or_payload) -> str:
    payload = (
        model_or_payload
        if isinstance(model_or_payload, dict)
        else encode_fitted_model(model_or_payload)
    )
    checked = validate_model_payload(payload)
    encoded = json.dumps(
        checked, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _components(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 4
        or value[0] not in "AM"
        or value[1] not in "NAM"
        or value[2] not in "NAM"
        or value[3] not in "DN"
    ):
        raise ArtifactError("AutoETS componentsが不正です")
    return value


def _integer(value: Any, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < minimum:
        raise ArtifactError("AutoETS整数値が不正です")
    return int(value)


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ArtifactError("AutoETS有限数値が不正です")
    return float(value)


def _array(value: Any, *, allow_nan: bool) -> list:
    array = np.asarray(value)
    if array.ndim not in (1, 2):
        raise ArtifactError("AutoETS配列の次元が不正です")
    result = []
    for item in array.tolist():
        if isinstance(item, list):
            result.append([_nullable_number(x, allow_nan=allow_nan) for x in item])
        else:
            result.append(_nullable_number(item, allow_nan=allow_nan))
    return result


def _decoded_array(value: Any, *, allow_nan: bool, dimensions: int) -> list:
    if not isinstance(value, list) or not value:
        raise ArtifactError("AutoETS配列が不正です")
    if dimensions == 1:
        if any(isinstance(x, list) for x in value):
            raise ArtifactError("AutoETS一次元配列が不正です")
        return [_nullable_number(x, allow_nan=allow_nan) for x in value]
    if any(not isinstance(row, list) or not row for row in value):
        raise ArtifactError("AutoETS二次元配列が不正です")
    width = len(value[0])
    if any(len(row) != width for row in value):
        raise ArtifactError("AutoETS二次元配列の幅が不一致です")
    return [[_nullable_number(x, allow_nan=allow_nan) for x in row] for row in value]


def _nullable_number(value: Any, *, allow_nan: bool) -> float | None:
    if value is None or (
        not isinstance(value, bool) and isinstance(value, Real) and math.isnan(float(value))
    ):
        if allow_nan:
            return None
        raise ArtifactError("AutoETS配列に欠損は指定できません")
    return _number(value)
