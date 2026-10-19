"""Leakage-controlled, common-target comparison of versioned history models."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd

from forecast_provider.providers.baseline_algorithms import point_forecast
from forecast_provider.providers.history_algorithms import (
    MODELS,
    VERSION,
    predict_path,
    seasonal_signal,
)

CURRENT = "seasonal_naive_7"
METHODS = [CURRENT, *MODELS]


def metrics(items):
    if not items:
        return {"count": 0, "mae": None, "wape": None, "mean_error": None}
    errors = np.array([r["actual"] - r["prediction"] for r in items], dtype=float)
    actual = np.array([r["actual"] for r in items], dtype=float)
    denom = np.abs(actual).sum()
    return {
        "count": len(items),
        "mae": float(np.abs(errors).mean()),
        "mean_error": float(errors.mean()),
        "wape": float(np.abs(errors).sum() / denom * 100) if denom > 0 else None,
    }


def validate(frame):
    required = {"unique_id", "ds", "y", "known_at", "unit"}
    if not required <= set(frame):
        raise ValueError("unique_id,ds,y,known_at,unitが必要です")
    result = frame.copy()
    if result[["unique_id", "ds", "known_at", "unit"]].isna().any().any():
        raise ValueError("対応キー・単位・日付・利用可能日時の欠損を確認してください")
    result["ds"] = pd.to_datetime(result["ds"], errors="raise").dt.normalize()
    result["known_at"] = pd.to_datetime(result["known_at"], utc=True, errors="raise")
    result["y"] = pd.to_numeric(result["y"], errors="raise")
    known_days = result["known_at"].dt.tz_convert("Asia/Tokyo").dt.tz_localize(None).dt.normalize()
    if (known_days < result["ds"]).any():
        raise ValueError("発生日前に実績が判明するデータは使用できません")
    if np.isinf(result["y"].to_numpy()).any() or (result["y"].dropna() < 0).any():
        raise ValueError("数量の不正値があります")
    if result.duplicated(["unique_id", "ds"]).any():
        raise ValueError("同じ商品・日付が重複しています")
    if result["unit"].nunique() != 1:
        raise ValueError("異なる単位は集計できません。単位ごとに分けて比較してください")
    if (result.groupby("unique_id")["unit"].nunique() != 1).any():
        raise ValueError("同じ系列に異なる単位が混在しています")
    return result.sort_values(["unique_id", "ds"]).reset_index(drop=True)


def quality(frame):
    summaries = []
    for uid, g in frame.groupby("unique_id", sort=True):
        observed = g[g["y"].notna()]
        start, end = g["ds"].min(), g["ds"].max()
        summaries.append(
            {
                "unique_id": str(uid),
                "unit": str(g["unit"].iloc[0]),
                "start": start.date().isoformat(),
                "end": end.date().isoformat(),
                "calendar_days": int((end - start).days + 1),
                "observed_days": len(observed),
                "missing_days": int((end - start).days + 1 - len(observed)),
                "zero_days": int((observed["y"] == 0).sum()),
                "weekday": {
                    str(k): {"mean": float(v["y"].mean()), "count": len(v)}
                    for k, v in observed.groupby(observed["ds"].dt.dayofweek)
                },
                "month": {
                    str(k): {"mean": float(v["y"].mean()), "count": len(v)}
                    for k, v in observed.groupby(observed["ds"].dt.month)
                },
                "annual": {
                    str(k): {"mean": float(v["y"].mean()), "count": len(v)}
                    for k, v in observed.groupby(observed["ds"].dt.year)
                },
                "seasonality": seasonal_signal(observed.set_index("ds")["y"]),
            }
        )
    return summaries


def backtest(
    frame,
    *,
    origins=None,
    horizon=14,
    origin_count=13,
    step=28,
    holdout_origins=4,
    unit_confirmed=False,
    provenance=None,
    evaluation_at=None,
    allow_unconfirmed_units=False,
):
    if horizon not in range(1, 29) or origin_count < 5 or step < horizon:
        raise ValueError("1〜28日の予測と重複しない5起点以上を指定してください")
    data = validate(frame)
    unconfirmed = bool(data["unit"].isin(["UNKNOWN", "UNCONFIRMED", ""]).any())
    if unconfirmed and not allow_unconfirmed_units:
        raise ValueError("単位未確認です。未確認単位の参考比較は仮定の明示確認が必要です")
    if unit_confirmed and unconfirmed:
        raise ValueError("単位が未確認です。元データとの対応を先に確認してください")
    if data.empty:
        raise ValueError("評価できる履歴がありません")
    freeze = (
        pd.Timestamp(evaluation_at)
        if evaluation_at is not None
        else min(pd.Timestamp.now(tz="UTC"), data["known_at"].max())
    )
    if freeze.tzinfo is None:
        raise ValueError("評価基準日時にはtimezoneが必要です")
    freeze = freeze.tz_convert("UTC")
    raw = data.to_csv(index=False, lineterminator="\n").encode()
    source_sha = hashlib.sha256(raw).hexdigest()
    last = data["ds"].max() - pd.Timedelta(days=horizon)
    origins = (
        sorted(pd.Timestamp(d).normalize() for d in origins)
        if origins is not None
        else [last - pd.Timedelta(days=step * i) for i in reversed(range(origin_count))]
    )
    if len(set(origins)) != len(origins) or len(origins) <= holdout_origins or holdout_origins < 1:
        raise ValueError("選定用と未使用holdout起点を分けてください")
    if any((b - a).days < horizon for a, b in pairwise(origins)):
        raise ValueError("起点の予測対象期間を重複させないでください")
    holdout = set(origins[-holdout_origins:])
    rows = []
    excluded = Counter()
    for uid, group in data.groupby("unique_id", sort=True):
        actual = group[group["known_at"] <= freeze].set_index("ds")["y"]
        for origin in origins:
            cutoff = (origin + pd.Timedelta(days=1)).tz_localize("Asia/Tokyo").tz_convert(
                "UTC"
            ) - pd.Timedelta(nanoseconds=1)
            past = group[(group["ds"] <= origin) & (group["known_at"] <= min(cutoff, freeze))]
            history = past.set_index("ds")["y"]
            targets = [origin + pd.Timedelta(days=i) for i in range(1, horizon + 1)]
            if history.notna().sum() < 28:
                excluded["HISTORY_LESS_THAN_28"] += horizon
                continue
            paths = {m: predict_path(history, origin, targets, m) for m in MODELS}
            for i, target in enumerate(targets):
                truth = actual.get(target, np.nan)
                if pd.isna(truth):
                    excluded["ACTUAL_MISSING"] += 1
                    continue
                current = point_forecast(history, target, i + 1, CURRENT)
                candidates = [
                    target - pd.Timedelta(days=7 * k)
                    for k in range((i + 1 + 6) // 7, (i + 1 + 6) // 7 + 4)
                ]
                used = next((d for d in candidates if pd.notna(history.get(d))), None)
                predictions = {
                    CURRENT: {
                        "yhat": current,
                        "used_start": used.date().isoformat() if used is not None else None,
                        "used_end": used.date().isoformat() if used is not None else None,
                        "used_count": 1 if current is not None else 0,
                        "seasonality_applied": False,
                    },
                    **{m: p[i] for m, p in paths.items()},
                }
                if any(p["yhat"] is None for p in predictions.values()):
                    excluded["NOT_COMMON_TO_ALL_METHODS"] += 1
                    continue
                for model, p in predictions.items():
                    rows.append(
                        {
                            "unique_id": str(uid),
                            "origin": origin.date().isoformat(),
                            "target_date": target.date().isoformat(),
                            "horizon": i + 1,
                            "model": model,
                            "prediction": p["yhat"],
                            "actual": float(truth),
                            "partition": "HOLDOUT" if origin in holdout else "SELECTION",
                            "used_start": p["used_start"],
                            "used_end": p["used_end"],
                            "used_count": p["used_count"],
                            "seasonality_applied": p["seasonality_applied"],
                            "available_start": history.index.min().date().isoformat(),
                            "available_end": history.index.max().date().isoformat(),
                            "available_count": int(history.notna().sum()),
                        }
                    )
    summary = {
        part: {
            m: metrics([r for r in rows if r["partition"] == part and r["model"] == m])
            for m in METHODS
        }
        for part in ["SELECTION", "HOLDOUT"]
    }
    selections = []
    for uid in sorted(data["unique_id"].unique()):
        subset = [r for r in rows if r["unique_id"] == uid]
        selection = {
            m: metrics([r for r in subset if r["partition"] == "SELECTION" and r["model"] == m])
            for m in METHODS
        }
        ranked = [m for m in METHODS if selection[m]["count"] >= horizon * 4]
        chosen = (
            min(ranked, key=lambda m: (selection[m]["mae"], METHODS.index(m)))
            if ranked
            else CURRENT
        )
        validation = {
            m: metrics([r for r in subset if r["partition"] == "HOLDOUT" and r["model"] == m])
            for m in METHODS
        }
        base, candidate = validation[CURRENT], validation[chosen]
        enough = base["count"] >= horizon * holdout_origins and candidate["count"] == base["count"]
        improved = bool(
            enough
            and candidate["mae"] < base["mae"]
            and candidate["wape"] is not None
            and base["wape"] is not None
            and candidate["wape"] < base["wape"]
        )
        selections.append(
            {
                "unique_id": str(uid),
                "selection_choice": chosen,
                "holdout_baseline": base,
                "holdout_candidate": candidate,
                "improved_on_holdout": improved,
                "recommended_model": chosen if improved else CURRENT,
                "adoption_status": "REVIEW_REQUIRED"
                if improved and unit_confirmed
                else "KEEP_BASELINE",
                "reason": "HOLDOUT_IMPROVED" if improved else "INSUFFICIENT_OR_NO_IMPROVEMENT",
                "configuration": {
                    "version": VERSION + "-" + chosen,
                    "provider_id": "builtin-baseline",
                    "model_name": chosen,
                    "preprocessing_version": "portable-daily-state-v1",
                    "seed": 7,
                    "resource_profile": "cpu-small",
                    "params": {},
                },
            }
        )
    settings = {
        "horizon": horizon,
        "origins": [o.date().isoformat() for o in origins],
        "holdout_origins": holdout_origins,
        "unit_confirmed": unit_confirmed,
        "quantity_unit": str(data["unit"].iloc[0]),
        "aggregation_status": "CONDITIONAL_UNCONFIRMED_UNITS" if unconfirmed else "SINGLE_UNIT",
        "allow_unconfirmed_units": allow_unconfirmed_units,
        "version": VERSION,
        "evaluation_at": freeze.isoformat(),
        "provenance_sha256": hashlib.sha256(
            json.dumps(provenance or {}, sort_keys=True).encode()
        ).hexdigest(),
    }
    choices = {r["unique_id"]: r["selection_choice"] for r in selections}
    frozen = [
        r for r in rows if r["partition"] == "HOLDOUT" and r["model"] == choices[r["unique_id"]]
    ]
    frozen_summary = metrics(frozen)
    study_id = hashlib.sha256(
        (source_sha + json.dumps(settings, sort_keys=True)).encode()
    ).hexdigest()
    return {
        "format": "history-comparison-v1",
        "study_id": study_id,
        "input_sha256": source_sha,
        "created_at": datetime.now(UTC).isoformat(),
        "settings": settings,
        "provenance": provenance or {},
        "summary": summary,
        "frozen_product_selection_holdout": frozen_summary,
        "quality": quality(data),
        "excluded_targets": dict(excluded),
        "selections": selections,
        "rows": rows,
        "by_target_month": {
            str(month): {
                m: metrics(
                    [
                        r
                        for r in rows
                        if r["model"] == m
                        and r["partition"] == "HOLDOUT"
                        and pd.Timestamp(r["target_date"]).month == month
                    ]
                )
                for m in METHODS
            }
            for month in range(1, 13)
        },
        "production_changed": False,
        "notice": "同一対象の選定期間と未使用holdoutで比較。実績や現行方式を上書きしません。",
    }


def save(result, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = dict(result)
    result["result_sha256"] = hashlib.sha256(
        json.dumps(
            {k: v for k, v in result.items() if k != "result_sha256"},
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    target = output / (result["study_id"] + ".json")
    if not target.exists():
        temp = target.with_suffix(".tmp")
        temp.write_text(
            json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temp.replace(target)
    return target


def main():
    import argparse

    parser = argparse.ArgumentParser(description="時点安全な履歴期間・方式比較")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--unit-confirmed", action="store_true")
    parser.add_argument("--allow-unconfirmed-units", action="store_true")
    parser.add_argument("--confirm-availability-assumption", action="store_true")
    args = parser.parse_args()
    provenance = json.loads(args.provenance.read_text("utf-8")) if args.provenance else {}
    if (
        provenance.get("availability_mode") == "FILE_DATE_ASSUMED"
        and not args.confirm_availability_assumption
    ):
        parser.error("ファイル日付を利用可能日時とする仮定の明示確認が必要です")
    frame = pd.read_csv(args.input, dtype={"unique_id": str, "unit": str})
    result = backtest(
        frame,
        unit_confirmed=args.unit_confirmed,
        provenance=provenance,
        allow_unconfirmed_units=args.allow_unconfirmed_units,
    )
    target = save(result, args.output)
    print(
        json.dumps(
            {
                "path": str(target),
                "summary": result["summary"],
                "series": len(result["quality"]),
                "rows": len(result["rows"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
