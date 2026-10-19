"""Versioned point-only history models, shared by worker and offline studies."""

from __future__ import annotations

import numpy as np
import pandas as pd

VERSION = "history-models-v1"
MODELS = {
    "history_weekday_28_v1": 28,
    "history_weekday_90_v1": 90,
    "history_weekday_365_v1": 365,
    "history_weekday_3y_v1": None,
    "history_seasonal_recent_3y_v1": None,
}


def window_start(origin, days=None):
    origin = pd.Timestamp(origin).normalize()
    return (
        origin - pd.Timedelta(days=days - 1)
        if days is not None
        else origin - pd.DateOffset(years=3) + pd.Timedelta(days=1)
    )


def seasonal_signal(history):
    """Require two complete, sufficiently observed, varying annual profiles."""
    frame = pd.DataFrame({"y": history.dropna()})
    if frame.empty:
        return {"applied": False, "reason": "NO_HISTORY"}
    frame["year"] = frame.index.year
    frame["month"] = frame.index.month
    grouped = frame.groupby(["year", "month"])["y"].agg(["mean", "count"])
    years = []
    for year, group in grouped.groupby(level=0):
        if len(group) == 12 and group["count"].min() >= 14 and group["mean"].mean() > 0:
            profile = group["mean"].to_numpy() / group["mean"].mean()
            if profile.std() >= 0.05:
                years.append((int(year), profile))
    if len(years) < 2:
        return {"applied": False, "reason": "TWO_ANNUAL_PROFILES_UNAVAILABLE"}
    correlation = float(np.corrcoef(years[-2][1], years[-1][1])[0, 1])
    return {
        "applied": bool(np.isfinite(correlation) and correlation >= 0.5),
        "correlation": correlation if np.isfinite(correlation) else None,
        "years": [years[-2][0], years[-1][0]],
        "reason": "REPEATABLE_PROFILE_CHECK",
    }


def predict_path(history, origin, targets, model):
    if model not in MODELS:
        raise ValueError("Unknown history model")
    origin = pd.Timestamp(origin).normalize()
    history = history.loc[
        (history.index >= window_start(origin, MODELS[model])) & (history.index <= origin)
    ]
    history = history.dropna().sort_index()
    if (history < 0).any() or not np.isfinite(history.to_numpy(dtype=float)).all():
        raise ValueError("History quantities must be finite and nonnegative")
    recent = history.loc[history.index >= window_start(origin, 28)]
    signal = (
        seasonal_signal(history) if model == "history_seasonal_recent_3y_v1" else {"applied": False}
    )
    result = []
    for target in targets:
        target = pd.Timestamp(target).normalize()
        if target <= origin:
            raise ValueError("Targets must be later than origin")
        selected = history[history.index.dayofweek == target.dayofweek]
        applied = False
        if model == "history_seasonal_recent_3y_v1":
            short = recent[recent.index.dayofweek == target.dayofweek]
            seasonal = selected[selected.index.month == target.month]
            applied = bool(
                signal["applied"]
                and len(seasonal) >= 6
                and len(set(seasonal.index.year)) >= 2
                and len(short) > 0
            )
            selected = pd.concat([short, seasonal]).sort_index() if applied else short
            value = (
                (float(short.mean()) + float(seasonal.mean())) / 2
                if applied
                else (float(short.mean()) if len(short) else None)
            )
        else:
            value = float(selected.mean()) if len(selected) else None
        result.append(
            {
                "target_date": target.date().isoformat(),
                "yhat": value,
                "used_start": selected.index.min().date().isoformat() if len(selected) else None,
                "used_end": selected.index.max().date().isoformat() if len(selected) else None,
                "used_count": len(selected.index.unique()),
                "seasonality_applied": applied,
                "input_start": history.index.min().date().isoformat() if len(history) else None,
                "input_end": history.index.max().date().isoformat() if len(history) else None,
                "input_count": len(history),
                "seasonality_evidence": signal,
            }
        )
    return result
