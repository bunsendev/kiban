"""MLForecast Ridgeの因果的前処理と移植可能な学習済み状態。"""

from __future__ import annotations

import hashlib
import json
import math
from numbers import Real
from typing import Any

import numpy as np
import pandas as pd

from ..artifacts.contracts import ArtifactError

PREPROCESSING_VERSION = "mlforecast-causal-ffill-lags-dow-v1"
MODEL_PARAMS = {"alpha": 1.0}
LAGS = (1, 7, 14, 28)
DATE_FEATURES = ("dayofweek",)
FEATURE_NAMES = (*(f"lag{lag}" for lag in LAGS), *DATE_FEATURES)
MODEL_FIELDS = {"alpha", "feature_names", "coefficients", "intercept"}

def fit_ridge(series: pd.Series, alpha: float) -> dict[str, Any]:
    """MLForecastで特徴量を生成し、決定論的なRidgeを学習する。"""
    from mlforecast import MLForecast
    from sklearn.linear_model import Ridge

    frame = pd.DataFrame(
        {"unique_id": "series", "ds": series.index, "y": series.to_numpy(dtype="float64")}
    )
    forecast = MLForecast(
        models={"ridge": Ridge(alpha=alpha, solver="cholesky")},
        freq="D",
        lags=list(LAGS),
        date_features=list(DATE_FEATURES),
    )
    forecast.fit(frame, static_features=[])
    fitted = forecast.models_["ridge"]
    state = {
        "alpha": float(alpha),
        "feature_names": [str(value) for value in fitted.feature_names_in_],
        "coefficients": [float(value) for value in fitted.coef_],
        "intercept": float(fitted.intercept_),
    }
    return validate_ridge_state(state)


def predict_ridge(state: dict[str, Any], series: pd.Series, horizon: int) -> np.ndarray:
    """保存済み係数を変更せず、MLForecastと同じ再帰的lag予測を行う。"""
    model = validate_ridge_state(state)
    values = series.to_numpy(dtype="float64").tolist()
    if len(values) < max(LAGS):
        raise ValueError("Ridge予測に必要なlag履歴がありません")
    last_date = series.index[-1]
    forecasts: list[float] = []
    coefficients = np.asarray(model["coefficients"], dtype="float64")
    for step in range(1, horizon + 1):
        target_date = last_date + pd.Timedelta(days=step)
        features = np.asarray(
            [*(values[-lag] for lag in LAGS), float(target_date.dayofweek)],
            dtype="float64",
        )
        prediction = float(model["intercept"] + np.dot(coefficients, features))
        if not math.isfinite(prediction):
            raise ValueError("Ridgeが有限な予測を返しませんでした")
        values.append(prediction)
        forecasts.append(prediction)
    return np.asarray(forecasts, dtype="float64")


def validate_ridge_state(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != MODEL_FIELDS:
        raise ArtifactError("MLForecast Ridge modelフィールド不一致")
    alpha = _number(payload["alpha"], minimum=0.0, strictly_greater=True)
    names = payload["feature_names"]
    coefficients = payload["coefficients"]
    if not isinstance(names, list) or tuple(names) != FEATURE_NAMES:
        raise ArtifactError("MLForecast Ridge feature_namesが不正です")
    if not isinstance(coefficients, list) or len(coefficients) != len(FEATURE_NAMES):
        raise ArtifactError("MLForecast Ridge coefficientsが不正です")
    checked = [_number(value) for value in coefficients]
    return {
        "alpha": alpha,
        "feature_names": list(FEATURE_NAMES),
        "coefficients": checked,
        "intercept": _number(payload["intercept"]),
    }


def model_signature(model: dict[str, Any]) -> str:
    checked = validate_ridge_state(model)
    encoded = json.dumps(
        checked, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(
    value: Any, *, minimum: float | None = None, strictly_greater: bool = False
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ArtifactError("MLForecast Ridge有限数値が不正です")
    number = float(value)
    if minimum is not None and (
        number <= minimum if strictly_greater else number < minimum
    ):
        raise ArtifactError("MLForecast Ridge数値の範囲が不正です")
    return number
