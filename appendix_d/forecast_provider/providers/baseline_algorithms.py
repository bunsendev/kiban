"""builtin baselineの点予測と時点安全な経験残差計算。"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from ..errors import ContractViolationError


def same_weekday_lags(horizon: int) -> list[int]:
    """対象日と同一曜日で、起点以前となる直近4回分のラグ日数。"""
    steps = math.ceil(horizon / 7)
    return [7 * k for k in range(steps, steps + 4)]


def point_forecast(
    history: pd.Series,
    target_date: pd.Timestamp,
    horizon: int,
    model_name: str,
) -> float | None:
    """history（起点以前のみ）からtarget_dateの点予測を返す。"""
    if model_name == "moving_average_28":
        origin = target_date - pd.Timedelta(days=horizon)
        window = history.reindex(pd.date_range(origin - pd.Timedelta(days=27), origin)).dropna()
        return float(window.mean()) if len(window) else None

    if model_name == "seasonal_naive_364":
        lags = [364 * math.ceil(horizon / 364)]
    else:
        lags = same_weekday_lags(horizon)

    values = []
    for lag in lags:
        observed = history.get(target_date - pd.Timedelta(days=lag))
        if observed is not None and not pd.isna(observed):
            values.append(float(observed))
    if not values:
        return None
    if model_name in ("seasonal_naive_7", "seasonal_naive_364"):
        return values[0]
    if model_name == "same_weekday_mean_4":
        return float(np.mean(values))
    raise ContractViolationError(f"未知のモデル指定です: {model_name}")


def residual_quantiles(
    series: pd.Series,
    model_name: str,
    horizons: list[int],
    quantiles: list[float],
) -> dict[tuple[int, float], float]:
    """ASSUMEDのTRAIN系列から経験残差分位を推定する。"""
    out: dict[tuple[int, float], float] = {}
    values = series.to_numpy(dtype="float64")
    for horizon in horizons:
        predictions = historical_forecast(values, horizon, model_name)
        _store_quantiles(out, horizon, values - predictions, quantiles)
    return out


def observed_residual_quantiles(
    frame: pd.DataFrame,
    model_name: str,
    horizons: list[int],
    quantiles: list[float],
    train_end: date,
) -> dict[tuple[int, float], float]:
    """各historical originの締切を再現してOBSERVED残差を推定する。

    target日の正解値は最終TRAIN締切までに到着したものだけを使う。予測に使う
    過去値はtarget-horizonを起点とし、その翌日00:00 JSTまでに到着した値へ
    限定する。これにより、後日訂正された履歴を過去起点へ遡及させない。
    """
    if "available_at" not in frame:
        raise ContractViolationError("OBSERVED区間予測にはavailable_atが必要です")
    available = frame["available_at"]
    if (
        not pd.api.types.is_datetime64_any_dtype(available)
        or getattr(available.dtype, "tz", None) is None
        or available.isna().any()
    ):
        raise ContractViolationError("available_atはtimezone付き・非欠損日時です")

    indexed = frame.set_index("ds")[["y", "available_at"]].sort_index()
    full_index = pd.date_range(indexed.index.min(), indexed.index.max(), freq="D")
    indexed = indexed.reindex(full_index)
    values = indexed["y"].to_numpy(dtype="float64")
    arrivals = indexed["available_at"]
    truth_cutoff = (pd.Timestamp(train_end) + pd.Timedelta(days=1)).tz_localize("Asia/Tokyo")
    truth = values.copy()
    truth[arrivals.isna().to_numpy() | arrivals.gt(truth_cutoff).to_numpy()] = np.nan

    out: dict[tuple[int, float], float] = {}
    for horizon in horizons:
        cutoffs = (full_index - pd.Timedelta(days=horizon - 1)).tz_localize("Asia/Tokyo")
        predictions = _observed_historical_forecast(
            values, arrivals, cutoffs, horizon, model_name
        )
        _store_quantiles(out, horizon, truth - predictions, quantiles)
    return out


def _store_quantiles(out, horizon, residuals, quantiles) -> None:
    residuals = residuals[~np.isnan(residuals)]
    if residuals.size < 10:
        return
    for quantile in quantiles:
        out[horizon, quantile] = float(np.quantile(residuals, quantile))


def _shift(values: np.ndarray, lag: int) -> np.ndarray:
    shifted = np.full(values.size, np.nan, dtype="float64")
    if lag < values.size:
        shifted[lag:] = values[: values.size - lag]
    return shifted


def _shift_arrivals(values: pd.Series, lag: int) -> pd.Series:
    return values.shift(lag)


def _observed_historical_forecast(
    values: np.ndarray,
    arrivals: pd.Series,
    cutoffs: pd.DatetimeIndex,
    horizon: int,
    model_name: str,
) -> np.ndarray:
    if model_name == "moving_average_28":
        lags = list(range(horizon, horizon + 28))
    elif model_name == "seasonal_naive_364":
        lags = [364 * math.ceil(horizon / 364)]
    else:
        lags = same_weekday_lags(horizon)

    candidates = []
    for lag in lags:
        shifted = _shift(values, lag)
        shifted_arrivals = _shift_arrivals(arrivals, lag)
        valid = shifted_arrivals.notna().to_numpy() & shifted_arrivals.le(cutoffs).to_numpy()
        shifted[~valid] = np.nan
        candidates.append(shifted)
    matrix = np.vstack(candidates)

    if model_name in ("seasonal_naive_7", "seasonal_naive_364"):
        result = np.full(values.size, np.nan, dtype="float64")
        for candidate in matrix:
            take = np.isnan(result) & ~np.isnan(candidate)
            result[take] = candidate[take]
        return result
    if model_name in ("moving_average_28", "same_weekday_mean_4"):
        valid = ~np.isnan(matrix)
        counts = valid.sum(axis=0)
        sums = np.where(valid, matrix, 0.0).sum(axis=0)
        return np.divide(
            sums,
            counts,
            out=np.full(values.size, np.nan, dtype="float64"),
            where=counts > 0,
        )
    raise ContractViolationError(f"未知のモデル指定です: {model_name}")


def historical_forecast(values: np.ndarray, horizon: int, model_name: str) -> np.ndarray:
    """対象日-horizon以前だけを使って各日のhistorical forecastを返す。"""
    if model_name == "moving_average_28":
        return (
            pd.Series(values)
            .rolling(28, min_periods=1)
            .mean()
            .shift(horizon)
            .to_numpy(dtype="float64")
        )

    if model_name == "seasonal_naive_364":
        lags = [364 * math.ceil(horizon / 364)]
    else:
        lags = same_weekday_lags(horizon)
    matrix = np.vstack([_shift(values, lag) for lag in lags])
    if model_name in ("seasonal_naive_7", "seasonal_naive_364"):
        result = np.full(values.size, np.nan, dtype="float64")
        for candidate in matrix:
            take = np.isnan(result) & ~np.isnan(candidate)
            result[take] = candidate[take]
        return result
    if model_name == "same_weekday_mean_4":
        valid = ~np.isnan(matrix)
        counts = valid.sum(axis=0)
        sums = np.where(valid, matrix, 0.0).sum(axis=0)
        return np.divide(
            sums,
            counts,
            out=np.full(values.size, np.nan, dtype="float64"),
            where=counts > 0,
        )
    raise ContractViolationError(f"未知のモデル指定です: {model_name}")
