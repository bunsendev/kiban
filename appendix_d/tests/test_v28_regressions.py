"""v2.8で固定する追加契約。v2.7レビューで再現した穴を回帰テスト化する。

1. runner が ProviderError 以外の例外で丸ごと落ちない（台帳と errors に残す）
2. 完全な run どうしの比較が、不完全な run の失敗に引きずられない
3. 比率系指標の単位を列名で明示する（wape_pct / bias_rate_pct）
4. reconcile_predictions のベクトル化版が同じ判定を返す
5. runner が known_future_columns を落とさず provider へ渡す
6. check_lint / make_release が動作する
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_builtin_baseline import make_context, make_dataset
from test_v26_regressions import fixture_comparison

from forecast_provider import ProviderConfig
from forecast_provider.errors import ContractViolationError
from forecast_provider.evaluation import (
    METRIC_KEYS,
    build_plan,
    compare_runs,
    metrics,
    reconcile_predictions,
)
from forecast_provider.providers import builtin_baseline as bb
from forecast_provider.runner import attach_known_future, available_history, run_fixed_baseline

ROOT = Path(__file__).resolve().parents[1]


def _three_series(days: int = 1096) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    dow = np.array([1.3, 1.0, 0.9, 1.0, 1.2, 0.6, 0.2])
    return pd.concat(
        [
            pd.DataFrame(
                {
                    "unique_id": uid,
                    "ds": dates,
                    "y": np.maximum(
                        0, (100 + i * 20) * dow[dates.dayofweek] + rng.normal(0, 5, days)
                    ).round(0),
                }
            )
            for i, uid in enumerate(["A__K", "B__K", "C__K"])
        ],
        ignore_index=True,
    )


def _dataset():
    return replace(
        make_dataset(("A__K", "B__K", "C__K")),
        test_end=pd.Timestamp("2026-03-31").date(),
    )


# ---------------------------------------------------------------------------
# 1. runner の例外処理
# ---------------------------------------------------------------------------


def test_runner_survives_unclassified_exception_and_records_it(monkeypatch) -> None:
    """ProviderError 以外（KeyError 等）でも run 全体は落ちず、台帳へ FAILED を残す。

    仕様書9.1: 未分類の例外は NonRetryable として扱い、run は継続する。
    実OSSは内部で ValueError / RuntimeError を普通に投げる。
    """
    data = _three_series()
    ds = _dataset()
    calls = {"n": 0}
    original = bb.BuiltinBaselineProvider.predict

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyError("ライブラリ内部のバグを模擬")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(bb.BuiltinBaselineProvider, "predict", flaky)
    result = run_fixed_baseline(
        data,
        ds,
        ProviderConfig(
            "builtin-baseline", "seasonal_naive_7", preprocessing_version="daily-nan-preserving-v1"
        ),
        make_context(),
        availability_mode="ASSUMED",
    )
    assert result["status"] == "PARTIAL"
    assert result["unclassified_error_count"] == 1
    err = next(e for e in result["errors"] if e["error"] == "UNCLASSIFIED_ERROR")
    assert err["exception_type"] == "KeyError"
    assert err["traceback"] and "KeyError" in err["traceback"]
    assert err["retryable"] is False
    # 失敗した起点は台帳で FAILED、それ以外は SUCCESS
    ledger = result["ledger"]
    assert ledger.status.eq("FAILED").sum() > 0
    assert ledger.status.eq("SUCCESS").sum() > 0


def test_runner_records_fit_failure_and_marks_all_planned_failed(monkeypatch) -> None:
    """学習段階の未分類例外も台帳へ残し、全予定を FAILED にする。"""
    data = _three_series()
    ds = _dataset()

    def crash(self, *args, **kwargs):
        raise RuntimeError("学習時のライブラリ障害を模擬")

    monkeypatch.setattr(bb.BuiltinBaselineProvider, "fit_parameters", crash)
    result = run_fixed_baseline(
        data,
        ds,
        ProviderConfig(
            "builtin-baseline", "seasonal_naive_7", preprocessing_version="daily-nan-preserving-v1"
        ),
        make_context(),
        availability_mode="ASSUMED",
    )
    assert result["status"] == "FAILED"
    assert result["ledger"].status.eq("FAILED").all()
    assert result["errors"][0]["origin_date"] is None
    assert result["errors"][0]["error"] == "UNCLASSIFIED_ERROR"


def test_runner_still_raises_contract_violation(monkeypatch) -> None:
    """契約違反は欠測へ変換せず、そのまま送出する（従来どおり）。"""
    data = _three_series()
    ds = _dataset()

    def violate(self, *args, **kwargs):
        raise ContractViolationError("契約違反を模擬")

    monkeypatch.setattr(bb.BuiltinBaselineProvider, "predict", violate)
    with pytest.raises(ContractViolationError):
        run_fixed_baseline(
            data,
            ds,
            ProviderConfig(
                "builtin-baseline",
                "seasonal_naive_7",
                preprocessing_version="daily-nan-preserving-v1",
            ),
            make_context(),
            availability_mode="ASSUMED",
        )


# ---------------------------------------------------------------------------
# 2. 完全な run どうしの比較
# ---------------------------------------------------------------------------


def test_official_runs_are_not_dragged_by_incomplete_run() -> None:
    """1つの run の失敗が、完全な run どうしの評価集合を縮めない。

    従来の common_metrics は全 run の共通集合で計算するため、最も弱い run に
    引きずられる。official_common_metrics は失敗のない run どうしの集合で計算する。
    """
    a, _, out, _, truth = fixture_comparison()
    damaged = out.iloc[3:]  # c だけ3件失敗
    r = compare_runs(
        {"a": a, "b": a, "c": a},
        {"a": out, "b": out, "c": damaged},
        truth,
        truth_version="v1",
    )
    # 従来の厳格判定は False のまま
    assert not r["ranking_ready"]
    # 完全な run は a, b。c は不完全
    assert r["official_runs"] == ["a", "b"]
    assert r["incomplete_runs"] == ["c"]
    assert r["official_ranking_ready"]
    # 全 run 共通集合は c の失敗で縮む
    assert r["scores"]["a"]["common_success_count"] == len(out) - 3
    # official 集合は縮まない
    assert r["scores"]["a"]["official_common_success_count"] == len(out)
    assert r["scores"]["b"]["official_common_success_count"] == len(out)
    assert r["scores"]["a"]["official_common_metrics"]["mae"] == 0
    # 不完全な run には official 指標がない（除外ではなく、own と成功率で表示する）
    assert r["scores"]["c"]["official_common_metrics"] is None
    assert r["scores"]["c"]["own_metrics"]["mae"] == 0
    assert r["scores"]["c"]["run_success_rate"] < 1.0


def test_own_metrics_use_only_that_runs_successes() -> None:
    a, _, out, _, truth = fixture_comparison()
    damaged = out.iloc[2:]
    r = compare_runs({"a": a, "b": a}, {"a": out, "b": damaged}, truth, truth_version="v1")
    # a 自身は全件成功しているので own は全件
    assert r["scores"]["a"]["truth_success_count"] == len(out)
    assert r["scores"]["a"]["own_metrics"]["mae"] == 0
    # b の own は自身の成功分だけ
    assert r["scores"]["b"]["truth_success_count"] == len(out) - 2


def test_official_ranking_not_ready_without_any_complete_run() -> None:
    a, _, out, _, truth = fixture_comparison()
    r = compare_runs({"a": a}, {"a": out.iloc[1:]}, truth, truth_version="v1")
    assert r["official_runs"] == []
    assert not r["official_ranking_ready"]


# ---------------------------------------------------------------------------
# 3. 指標の単位
# ---------------------------------------------------------------------------


def test_metric_keys_carry_units() -> None:
    r = metrics(np.array([0, 10]), np.array([5, 5]))
    assert set(r) == set(METRIC_KEYS)
    assert "wape" not in r and "bias_rate" not in r
    assert r["wape_pct"] == 100.0
    assert r["bias_rate_pct"] == 0.0
    assert r["bias"] == 0.0


# ---------------------------------------------------------------------------
# 4. reconcile のベクトル化
# ---------------------------------------------------------------------------


def test_reconcile_interval_status_vectorized_matches_semantics() -> None:
    ds, _, out, _, _ = fixture_comparison()
    plan = build_plan(ds)
    expected = {0.1, 0.9}
    # 先頭2キーだけ全quantileを出す
    keys = out.iloc[:2][["unique_id", "origin_date", "target_date", "horizon"]]
    quant = pd.concat(
        [
            keys.assign(forecast_kind="QUANTILE", quantile=q, yhat_raw=10.0, yhat=10.0)
            for q in sorted(expected)
        ],
        ignore_index=True,
    )
    result = pd.concat([out, quant], ignore_index=True)
    ledger = reconcile_predictions(plan, result, expected_quantiles=expected)
    assert ledger.interval_status.eq("SUCCESS").sum() == 2
    assert ledger.interval_status.eq("UNAVAILABLE").sum() == len(plan) - 2
    assert ledger.status.eq("SUCCESS").all()

    # 部分出力は契約違反（従来どおり）
    partial = pd.concat([out, quant.iloc[:1]], ignore_index=True)
    with pytest.raises(ContractViolationError):
        reconcile_predictions(plan, partial, expected_quantiles=expected)

    # 要求外 quantile も契約違反
    wrong = pd.concat([out, quant.assign(quantile=0.3)], ignore_index=True)
    with pytest.raises(ContractViolationError):
        reconcile_predictions(plan, wrong, expected_quantiles=expected)

    # quantile を1件も出さない場合は全件 UNAVAILABLE
    none = reconcile_predictions(plan, out, expected_quantiles=expected)
    assert none.interval_status.eq("UNAVAILABLE").all()


# ---------------------------------------------------------------------------
# 5. known_future_columns の通過
# ---------------------------------------------------------------------------


def test_runner_passes_known_future_columns_through() -> None:
    data = _three_series()
    ds = replace(_dataset(), known_future_columns=("promo_flag",))
    versions = data[["unique_id", "ds"]].assign(
        feature="promo_flag",
        value=(data.ds.dt.day == 1).astype(float),
        known_at=pd.Timestamp("2023-12-01", tz="Asia/Tokyo"),
    )
    hist = available_history(
        data,
        pd.Timestamp("2026-02-01"),
        availability_mode="ASSUMED",
        known_future_columns=("promo_flag",),
        feature_versions=versions,
    )
    assert "promo_flag" in hist.columns
    plan = build_plan(ds)
    future = attach_known_future(plan, data, ("promo_flag",), feature_versions=versions)
    assert future.promo_flag.notna().all()
    with pytest.raises(ContractViolationError):
        attach_known_future(
            plan,
            data,
            ("promo_flag",),
            feature_versions=versions[versions.ds < pd.Timestamp("2026-02-01")],
        )
    with pytest.raises(ContractViolationError):
        available_history(
            data,
            pd.Timestamp("2026-02-01"),
            availability_mode="ASSUMED",
            known_future_columns=("promo_flag",),
        )
    result = run_fixed_baseline(
        data,
        ds,
        ProviderConfig(
            "builtin-baseline", "seasonal_naive_7", preprocessing_version="daily-nan-preserving-v1"
        ),
        make_context(),
        availability_mode="ASSUMED",
        feature_versions=versions,
    )
    assert result["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 6. 配布ゲート
# ---------------------------------------------------------------------------


def test_check_lint_passes_on_repository() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "check_lint.py")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout


def test_make_release_check_matches_sums() -> None:
    sums_path = ROOT / "SHA256SUMS.json"
    if not sums_path.exists():
        pytest.skip("SHA256SUMS.json 未生成")
    sums = json.loads(sums_path.read_text(encoding="utf-8"))
    # 日本語ファイル名が正しいキーで記録されている
    assert any("付録D" in k for k in sums)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "make_release.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout
