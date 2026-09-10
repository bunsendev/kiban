"""予定表・失敗照合・共通キー評価。実績の欠損と予測失敗は別管理する。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

import numpy as np
import pandas as pd

from .contracts import ForecastDataset
from .errors import ContractViolationError
from .frames import TARGET_KEY, validate_future_frame, validate_predict_frame, validate_train_frame


def build_plan(dataset: ForecastDataset) -> pd.DataFrame:
    rows = [
        (uid, pd.Timestamp(origin), pd.Timestamp(origin) + pd.Timedelta(days=h), h)
        for origin in dataset.origin_dates()
        for uid in dataset.unique_ids
        for h in range(1, dataset.max_horizon + 1)
        if pd.Timestamp(origin) + pd.Timedelta(days=h) <= pd.Timestamp(dataset.test_end)
    ]
    return pd.DataFrame(rows, columns=TARGET_KEY)


def primary_plan(dataset: ForecastDataset) -> pd.DataFrame:
    """成功結果から選ばず、予定表から最新起点を先に選ぶ。"""
    plan = build_plan(dataset)
    return (
        plan[plan.horizon.le(dataset.primary_horizon_max)]
        .sort_values("origin_date")
        .drop_duplicates(["unique_id", "target_date"], keep="last")
        .reset_index(drop=True)
    )


def reconcile_predictions(
    plan: pd.DataFrame, result: pd.DataFrame, *, expected_quantiles: set[float] | None = None
) -> pd.DataFrame:
    """空出力・系列除外もFAILEDへ。区間未提供は点予測失敗と分ける。"""
    validate_future_frame(plan)
    validate_predict_frame(result, allow_empty=True)
    actual_keys = result[TARGET_KEY].drop_duplicates()
    if not actual_keys.empty:
        extra = actual_keys.merge(plan[TARGET_KEY], on=TARGET_KEY, how="left", indicator=True)
        if extra._merge.eq("left_only").any():
            raise ContractViolationError("予定外の予測出力")
    point = result[result.forecast_kind.eq("POINT")][[*TARGET_KEY, "yhat_raw", "yhat"]]
    if point.empty:
        ledger = plan.copy()
        ledger["yhat_raw"] = np.nan
        ledger["yhat"] = np.nan
    else:
        ledger = plan.merge(point, on=TARGET_KEY, how="left", validate="one_to_one")
    ledger["status"] = np.where(ledger.yhat.notna(), "SUCCESS", "FAILED")
    ledger["reason"] = np.where(ledger.yhat.notna(), "", "NO_POINT_OUTPUT")
    ledger["interval_status"] = "NOT_REQUESTED"
    if expected_quantiles:
        quant = result[result.forecast_kind.eq("QUANTILE")]
        if not quant.empty:
            if not set(quant["quantile"]).issubset(expected_quantiles):
                raise ContractViolationError("要求外のquantile出力")
            # 対象キーごとの出力quantile集合。全件出力か0件だけを許す（部分出力は契約違反）。
            per_key = quant.groupby(TARGET_KEY)["quantile"].agg(lambda s: frozenset(s))
            complete = per_key.eq(frozenset(expected_quantiles))
            if not complete.all():
                raise ContractViolationError("要求quantileの一部だけが出力されています")
            done = per_key[complete].reset_index()[TARGET_KEY]
            done["interval_status"] = "SUCCESS"
            ledger = ledger.merge(done, on=TARGET_KEY, how="left", suffixes=("", "_q"))
            ledger["interval_status"] = ledger["interval_status_q"].fillna("UNAVAILABLE")
            ledger = ledger.drop(columns=["interval_status_q"])
        else:
            ledger["interval_status"] = "UNAVAILABLE"
    return ledger


METRIC_KEYS: tuple[str, ...] = ("wape_pct", "mae", "rmse", "bias", "bias_rate_pct", "under", "over")


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if actual.shape != predicted.shape or actual.ndim != 1:
        raise ContractViolationError("評価配列の長さ・次元不一致")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ContractViolationError("評価配列に欠損・無限大")
    if np.any(actual < 0) or np.any(predicted < 0):
        raise ContractViolationError("評価値は非負で指定します")
    if not actual.size:
        return dict.fromkeys(METRIC_KEYS)
    e = predicted - actual
    denominator = actual.sum()
    return {
        # 比率系は単位を列名で明示する（DB保存時の曖昧さを排除）。
        # wape_pct / bias_rate_pct はパーセント。仕様書9章の比率定義×100。
        "wape_pct": float(np.abs(e).sum() / denominator * 100) if denominator else None,
        "mae": float(np.abs(e).mean()),
        "rmse": float(np.sqrt(np.mean(e**2))),
        "bias": float(e.sum()),
        "bias_rate_pct": float(e.sum() / denominator * 100) if denominator else None,
        "under": float(np.maximum(-e, 0).sum()),
        "over": float(np.maximum(e, 0).sum()),
    }


def compare_runs(
    datasets: Mapping[str, ForecastDataset],
    outputs: Mapping[str, pd.DataFrame],
    truth: pd.DataFrame,
    *,
    truth_version: str,
    mode: str = "horizon",
    horizon: int | None = None,
    official_eligible_runs: set[str] | None = None,
) -> dict:
    """同一予定キーを抽出し共通成功集合で参考比較。失敗ありは正式順位不可。

    truth: unique_id, ds, y。時点別入力ではなく評価用に凍結した確定実績。
    mode=primaryは運用profile一致必須。horizonは明示時に絞り込む。
    """
    if not datasets or set(datasets) != set(outputs) or not truth_version:
        raise ContractViolationError("run定義・結果・truth版を指定します")
    if official_eligible_runs is not None and not official_eligible_runs.issubset(datasets):
        raise ContractViolationError("適合済みrun集合に未知のrunが含まれます")
    if mode not in ("horizon", "primary"):
        raise ContractViolationError("評価mode不正")
    if any(name in [*TARGET_KEY, "y"] for name in datasets):
        raise ContractViolationError("run名が予約列名と重複")
    base = next(iter(datasets.values()))
    for ds in datasets.values():
        if ds.evaluation_scope != base.evaluation_scope:
            raise ContractViolationError("評価scope不一致")
        if mode == "primary" and not base.full_period_comparable_with(ds):
            raise ContractViolationError("通期profile不一致")
    if horizon is not None and (
        isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1
    ):
        raise ContractViolationError("評価horizon不正")
    validate_train_frame(truth)
    ledgers = {}
    for name, ds in datasets.items():
        full = reconcile_predictions(build_plan(ds), outputs[name])
        if mode == "primary":
            full = primary_plan(ds).merge(full, on=TARGET_KEY, validate="one_to_one")
        if horizon is not None:
            full = full[full.horizon.eq(horizon)]
        ledgers[name] = full
    shared = next(iter(ledgers.values()))[TARGET_KEY]
    for ledger in ledgers.values():
        shared = shared.merge(ledger[TARGET_KEY], on=TARGET_KEY, validate="one_to_one")
    shared = shared.sort_values(TARGET_KEY).reset_index(drop=True)
    evaluated = shared.merge(
        truth[["unique_id", "ds", "y"]].rename(columns={"ds": "target_date"}),
        on=["unique_id", "target_date"],
        how="left",
        validate="many_to_one",
    )
    eligible = evaluated[evaluated.y.notna()].copy()
    combined = eligible
    for name, ledger in ledgers.items():
        combined = combined.merge(
            ledger[[*TARGET_KEY, "yhat"]].rename(columns={"yhat": name}),
            on=TARGET_KEY,
            validate="one_to_one",
        )
    # 内部列との衝突を避ける。
    common = combined.dropna(subset=list(datasets))
    signature = {
        "scope": base.evaluation_scope,
        "truth": truth_version,
        "mode": mode,
        "horizon": horizon,
        "runs": sorted(datasets),
        "scheduled": shared.to_dict("records"),
        "success": common[TARGET_KEY].to_dict("records"),
    }
    comparison_id = hashlib.sha256(
        json.dumps(signature, default=str, sort_keys=True).encode()
    ).hexdigest()
    scores = {}
    all_runs_complete = True
    official_runs: list[str] = []
    for name in datasets:
        ledger = ledgers[name]
        run_success = int(ledger.status.eq("SUCCESS").sum())
        run_planned = len(ledger)
        run_failure = run_planned - run_success

        shared_run = shared.merge(
            ledger[[*TARGET_KEY, "status", "yhat"]], on=TARGET_KEY, validate="one_to_one"
        )
        shared_success = int(shared_run.status.eq("SUCCESS").sum())
        truth_success = int(combined[name].notna().sum())
        own_all = ledger.merge(
            truth[["unique_id", "ds", "y"]].rename(columns={"ds": "target_date"}),
            on=["unique_id", "target_date"],
            how="left",
            validate="many_to_one",
        )
        own_eligible = own_all[own_all.y.notna()]
        own = own_eligible[own_eligible.yhat.notna()]
        conformance_ok = official_eligible_runs is None or name in official_eligible_runs
        official = bool(len(own_eligible)) and run_failure == 0 and conformance_ok
        all_runs_complete = all_runs_complete and run_failure == 0
        if official:
            official_runs.append(name)

        # own: そのrun自身がtruth上で成功した集合。他runの失敗に影響されない。

        scores[name] = {
            "run_planned_count": run_planned,
            "run_success_count": run_success,
            "run_failure_count": run_failure,
            "run_success_rate": run_success / run_planned if run_planned else None,
            "shared_planned_count": len(shared),
            "shared_success_count": shared_success,
            "shared_failure_count": len(shared) - shared_success,
            "truth_eligible_count": len(eligible),
            "truth_missing_count": len(shared) - len(eligible),
            "truth_success_count": truth_success,
            "common_success_count": len(common),
            "official_eligible": official,
            "own_planned_count": run_planned,
            "own_truth_eligible_count": len(own_eligible),
            "own_truth_missing_count": len(own_all) - len(own_eligible),
            "own_success_count": len(own),
            "own_metrics": metrics(own.y.to_numpy(), own.yhat.to_numpy()),
            "common_metrics": metrics(common.y.to_numpy(), common[name].to_numpy()),
            "official_common_success_count": None,
            "official_common_metrics": None,
        }

    # official集合: 失敗のないrunどうしの共通集合。
    # 不完全なrunが1つあっても、完全なrunどうしの比較は成立させる。
    official_plan = pd.DataFrame(columns=TARGET_KEY)
    if official_runs:
        official_plan = ledgers[official_runs[0]][TARGET_KEY].copy()
        for name in official_runs[1:]:
            official_plan = official_plan.merge(
                ledgers[name][TARGET_KEY], on=TARGET_KEY, validate="one_to_one"
            )
        official_plan = official_plan.sort_values(TARGET_KEY).reset_index(drop=True)
    if official_plan.empty:
        official_common = eligible.iloc[:0].copy()
    else:
        official_common = official_plan.merge(
            truth[["unique_id", "ds", "y"]].rename(columns={"ds": "target_date"}),
            on=["unique_id", "target_date"],
            how="left",
            validate="many_to_one",
        )
        official_common = official_common[official_common.y.notna()]
    for name in official_runs:
        official_common = official_common.merge(
            ledgers[name][[*TARGET_KEY, "yhat"]].rename(columns={"yhat": name}),
            on=TARGET_KEY,
            validate="one_to_one",
        )
    official_common = (
        official_common.dropna(subset=official_runs) if official_runs else eligible.iloc[:0]
    )
    for name in official_runs:
        scores[name]["official_common_success_count"] = len(official_common)
        scores[name]["official_common_metrics"] = metrics(
            official_common.y.to_numpy(), official_common[name].to_numpy()
        )

    official_signature = {
        "policy": "official_common_v2.9",
        "scope": base.evaluation_scope,
        "truth": truth_version,
        "mode": mode,
        "horizon": horizon,
        "runs": sorted(official_runs),
        "planned": official_plan.to_dict("records"),
        "eligible": official_common[TARGET_KEY].to_dict("records"),
    }
    official_id = hashlib.sha256(
        json.dumps(official_signature, default=str, sort_keys=True).encode()
    ).hexdigest()
    return {
        "comparison_set_id": comparison_id,
        "official_comparison_set_id": official_id,
        "official_planned_count": len(official_plan),
        "official_truth_eligible_count": len(official_common),
        "official_truth_missing_count": len(official_plan) - len(official_common),
        "scores": scores,
        # ranking_ready: 全runが完全で、全run共通集合がtruth全件を覆う（従来どおりの厳格判定）
        "ranking_ready": (
            bool(len(eligible))
            and all_runs_complete
            and len(common) == len(eligible)
            and all(score["official_eligible"] for score in scores.values())
        ),
        # official_ranking_ready: 完全なrunが1つ以上あれば、それらの間でランキングを成立させる。
        # 不完全なrunは除外せず、成功率と own_metrics を併記して表示する（仕様書0.1）。
        "official_runs": official_runs,
        "official_ranking_ready": bool(len(official_common)) and len(official_runs) >= 2,
        "official_evaluation_ready": bool(len(official_common)) and bool(official_runs),
        "incomplete_runs": [
            name for name, score in scores.items() if score["run_failure_count"] > 0
        ],
        "official_excluded_runs": [name for name in datasets if name not in official_runs],
    }


def cumulative_evaluation(ledger: pd.DataFrame, truth: pd.DataFrame, window: int) -> pd.DataFrame:
    """起点ごとの1..window日累計。途中欠測・失敗・年末打切りを明示する。"""
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ContractViolationError("累計日数不正")
    validate_train_frame(truth)
    rows = []
    for (uid, origin), group in ledger.groupby(["unique_id", "origin_date"]):
        part = group[group.horizon.between(1, window)]
        if set(part.horizon) != set(range(1, window + 1)):
            rows.append((uid, origin, window, "INCOMPLETE_WINDOW", np.nan, np.nan))
            continue
        merged = part.merge(
            truth.rename(columns={"ds": "target_date"}),
            on=["unique_id", "target_date"],
            how="left",
            validate="many_to_one",
        )
        status = (
            "MISSING_TRUTH"
            if merged.y.isna().any()
            else "FAILED_PREDICTION"
            if merged.yhat.isna().any()
            else "SUCCESS"
        )
        rows.append(
            (
                uid,
                origin,
                window,
                status,
                float(merged.y.sum()) if status == "SUCCESS" else np.nan,
                float(merged.yhat.sum()) if status == "SUCCESS" else np.nan,
            )
        )
    return pd.DataFrame(
        rows,
        columns=["unique_id", "origin_date", "window", "status", "actual_sum", "predicted_sum"],
    )
