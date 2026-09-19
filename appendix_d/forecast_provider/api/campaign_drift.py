"""比較可能なキャンペーン結果の時系列変化を集計する。"""

from __future__ import annotations

import hashlib
import json
from datetime import date


def dataset_profile(manifest: dict) -> dict:
    """識別子を公開せず、比較対象と期間幅を固定するプロフィールを返す。"""
    unique_ids = sorted(str(value) for value in manifest["unique_ids"])
    known_future = sorted(str(value) for value in manifest.get("known_future_columns", []))
    return {
        "population_hash": _digest(unique_ids),
        "population_size": len(unique_ids),
        "known_future_hash": _digest(known_future),
        "train_days": _days(manifest["train_start"], manifest["train_end"]),
        "test_days": _days(manifest["test_start"], manifest["test_end"]),
        "availability_mode": manifest["availability_mode"],
    }


def model_profile(definition: dict) -> str:
    """snapshotだけを除外し、モデル・前処理・学習条件を指紋化する。"""
    return _digest({key: value for key, value in definition.items() if key != "snapshot_id"})


def summarize_model_drift(tests: list[dict]) -> dict:
    """同一プロフィールの直近2期間について、公式指標の差分を返す。"""
    buckets: dict[str, dict] = {}
    for test in tests:
        for model in test["models"]:
            if (
                not model["official_eligible"]
                or model["wape_pct"] is None
                or model["rank"] is None
            ):
                continue
            profile = _comparison_profile(test, model)
            profile_id = _digest(profile)
            bucket = buckets.setdefault(profile_id, {"profile": profile, "periods": {}})
            sample = _sample(test, model)
            period = (test["test_start"], test["test_end"])
            current = bucket["periods"].get(period)
            if current is None or _sample_order(sample) > _sample_order(current):
                bucket["periods"][period] = sample

    series = []
    for profile_id, bucket in buckets.items():
        periods = sorted(bucket["periods"].values(), key=_sample_order)
        latest = periods[-1]
        previous = periods[-2] if len(periods) > 1 else None
        series.append(_series(profile_id, bucket["profile"], periods, previous, latest))
    direction_order = {
        "WAPE_UP": 0,
        "WAPE_DOWN": 1,
        "UNCHANGED": 2,
        "INSUFFICIENT_HISTORY": 3,
    }
    series.sort(
        key=lambda item: (
            direction_order[item["direction"]],
            item["provider_id"],
            item["model_id"],
            item["comparison_profile_id"],
        )
    )
    return {
        "series_count": len(series),
        "comparable_series_count": sum(item["history_count"] >= 2 for item in series),
        "series": series,
    }


def _comparison_profile(test: dict, model: dict) -> dict:
    return {
        "provider_id": model["provider_id"],
        "model_id": model["model_id"],
        "population_hash": test["population_hash"],
        "known_future_hash": test["known_future_hash"],
        "population_size": test["population_size"],
        "train_days": test["train_days"],
        "test_days": test["test_days"],
        "availability_mode": test["availability_mode"],
        "mode": test["mode"],
        "horizon": test["horizon"],
        "origin_interval_days": test["origin_interval_days"],
        "max_horizon": test["max_horizon"],
        "primary_horizon_max": test["primary_horizon_max"],
        "model_profile_hash": model["model_profile_hash"],
    }


def _sample(test: dict, model: dict) -> dict:
    return {
        "campaign_id": test["campaign_id"],
        "selection_version": test["selection_version"],
        "test_start": test["test_start"],
        "test_end": test["test_end"],
        "created_at": test["created_at"],
        "wape_pct": model["wape_pct"],
        "bias_rate_pct": model["bias_rate_pct"],
        "success_rate_pct": model["success_rate_pct"],
        "rank": model["rank"],
    }


def _sample_order(sample: dict) -> tuple:
    return (
        sample["test_end"],
        sample["test_start"],
        sample["created_at"],
        sample["campaign_id"],
    )


def _series(profile_id: str, profile: dict, periods: list[dict], previous, latest) -> dict:
    wape_change = _change(previous, latest, "wape_pct")
    direction = "INSUFFICIENT_HISTORY"
    if previous is not None:
        if wape_change > 0:
            direction = "WAPE_UP"
        elif wape_change < 0:
            direction = "WAPE_DOWN"
        else:
            direction = "UNCHANGED"
    return {
        "provider_id": profile["provider_id"],
        "model_id": profile["model_id"],
        "comparison_profile_id": profile_id,
        "population_size": profile["population_size"],
        "train_days": profile["train_days"],
        "test_days": profile["test_days"],
        "availability_mode": profile["availability_mode"],
        "mode": profile["mode"],
        "horizon": profile["horizon"],
        "origin_interval_days": profile["origin_interval_days"],
        "max_horizon": profile["max_horizon"],
        "primary_horizon_max": profile["primary_horizon_max"],
        "history_count": len(periods),
        "previous": previous,
        "latest": latest,
        "wape_change_pct_points": wape_change,
        "wape_relative_change_pct": _relative_change(previous, latest, "wape_pct"),
        "abs_bias_change_pct_points": _absolute_change(previous, latest, "bias_rate_pct"),
        "success_rate_change_pct_points": _change(previous, latest, "success_rate_pct"),
        "rank_change": _change(previous, latest, "rank"),
        "period_gap_days": _period_gap(previous, latest),
        "direction": direction,
    }


def _change(previous, latest, key: str):
    if previous is None or previous[key] is None or latest[key] is None:
        return None
    return latest[key] - previous[key]


def _absolute_change(previous, latest, key: str):
    if previous is None or previous[key] is None or latest[key] is None:
        return None
    return abs(latest[key]) - abs(previous[key])


def _relative_change(previous, latest, key: str):
    change = _change(previous, latest, key)
    if change is None or previous[key] == 0:
        return None
    return change / previous[key] * 100


def _period_gap(previous, latest):
    if previous is None:
        return None
    latest_start = date.fromisoformat(latest["test_start"])
    previous_end = date.fromisoformat(previous["test_end"])
    return (latest_start - previous_end).days - 1


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def _digest(value) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()
