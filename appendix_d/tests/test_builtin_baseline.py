"""builtin-baseline の契約適合性テスト（v2.7契約）

本ファイルは4.3のアダプター適合試験および受入基準に対応する。
  適合試験1  TRAIN期間だけでパラメータを学習できる
  適合試験2  パラメータを変更せず、起点以前の実績を入力へ反映できる
  適合試験3  起点より後の実績を変更しても当該起点の予測が変わらない（AC-07）
  適合試験4  1回の呼び出しで horizon 1〜15 を出力できる
  適合試験5  ライブラリ名・バージョン・設定・seed・試験結果を保存できる

新規プロバイダーを追加する場合、本ファイルをテンプレートとして
同等のテストを用意すること。契約テストの通過をレビュー条件とし、
結果を provider_conformance_tests へ保存する。
"""

from __future__ import annotations

import logging
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forecast_provider import (
    ForecastDataset,
    ProviderConfig,
    RunContext,
    registry,
)
from forecast_provider.errors import ContractViolationError
from forecast_provider.frames import (
    quantiles_from_interval_levels,
    validate_predict_frame,
    validate_train_frame,
)

HORIZONS = list(range(1, 16))
INTERVAL_LEVELS = (0.8, 0.95)
TRAIN_END = pd.Timestamp("2025-12-31")
TEST_END = date(2026, 12, 31)


# ---------------------------------------------------------------------------
# テスト補助
# ---------------------------------------------------------------------------


def make_context(seed: int = 42) -> RunContext:
    tmp = Path(tempfile.mkdtemp())
    return RunContext(
        run_id="run_test",
        experiment_id="exp_test",
        seed=seed,
        deadline=datetime.now(UTC) + timedelta(hours=1),
        input_dir=tmp,
        output_dir=tmp,
        resource_profile="cpu-standard",
        logger=logging.getLogger("test"),
    )


def make_dataset(
    unique_ids: tuple[str, ...],
    origin_interval_days: int = 10,
    primary_horizon_max: int = 10,
) -> ForecastDataset:
    return ForecastDataset(
        dataset_snapshot_id="dss_test",
        selection_version="sel_test",
        unique_ids=unique_ids,
        train_start=date(2024, 1, 1),
        train_end=TRAIN_END.date(),
        test_start=date(2026, 1, 1),
        test_end=TEST_END,
        origin_interval_days=origin_interval_days,
        max_horizon=15,
        primary_horizon_max=primary_horizon_max,
    )


def make_series(unique_ids: list[str], start: str, days: int, *, seed: int = 0) -> pd.DataFrame:
    """検証用の日次系列。曜日変動と緩やかな水準変化を持つ。"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=days, freq="D")
    dow = np.array([1.3, 1.0, 0.9, 1.0, 1.2, 0.6, 0.2])
    frames = []
    for i, uid in enumerate(unique_ids):
        base = 100.0 + 20.0 * i
        y = np.maximum(
            0.0,
            base * dow[dates.dayofweek] + np.linspace(0, 15, days) + rng.normal(0, 5, days),
        ).round(0)
        frames.append(pd.DataFrame({"unique_id": uid, "ds": dates, "y": y}))
    return pd.concat(frames, ignore_index=True)


def make_future(unique_ids, origin: pd.Timestamp, horizons: list[int]) -> pd.DataFrame:
    """予測対象の骨格。実績列 y を含めてはならない。"""
    return pd.DataFrame(
        [
            {
                "unique_id": uid,
                "origin_date": origin,
                "target_date": origin + pd.Timedelta(days=h),
                "horizon": h,
            }
            for uid in sorted(unique_ids)
            for h in horizons
        ]
    )


def run_once(
    data: pd.DataFrame,
    origin: pd.Timestamp,
    model: str = "seasonal_naive_7",
    seed: int = 42,
) -> pd.DataFrame:
    """fit_parameters → refresh_context → predict の一連の流れ。

    パラメータ学習は TRAIN 期間のみ。コンテキスト更新は起点まで。
    """
    provider = registry.create("builtin-baseline")
    ctx = make_context(seed=seed)
    config = ProviderConfig(
        provider_id="builtin-baseline",
        model=model,
        interval_levels=INTERVAL_LEVELS,
    )
    train = data[data["ds"] <= TRAIN_END]
    history = data[data["ds"] <= origin]
    uids = sorted(data["unique_id"].unique())

    dataset = make_dataset(tuple(uids))
    model_ref = provider.fit_parameters(train, dataset, config, ctx)
    context_ref = provider.refresh_context(model_ref, history, origin.date(), ctx)
    future = make_future(uids, origin, HORIZONS)
    out = provider.predict(model_ref, context_ref, future, HORIZONS, ctx)
    provider.cleanup(ctx)
    return out


# ---------------------------------------------------------------------------
# テスト本体
# ---------------------------------------------------------------------------


def test_metadata_and_registry() -> None:
    metas = registry.list_metadata()
    assert any(m.provider_id == "builtin-baseline" for m in metas)
    meta = registry.create("builtin-baseline").metadata()
    assert meta.get_model("seasonal_naive_7").accepts_horizon(15)
    assert meta.capabilities.supports_context_refresh
    assert not meta.capabilities.requires_parameter_refit
    # 適合試験5: ライブラリ名・バージョン・実依存バージョンを保存できる
    assert meta.library_name and meta.library_version
    assert {name for name, _ in meta.runtime_dependencies} == {"pandas", "numpy"}


def test_capabilities_imply_primary_ranking_eligibility() -> None:
    """5章: パラメータ固定でコンテキスト更新できる場合のみ主ランキング候補。"""
    caps = registry.create("builtin-baseline").metadata().capabilities
    assert caps.eligible_for_primary_ranking


def test_origin_dates_follow_generation_rule() -> None:
    """6.1: origin(k) = train_end + 10k、条件 origin < test_end。"""
    dataset = make_dataset(("A__KAZO",))
    origins = dataset.origin_dates()
    assert origins[0] == TRAIN_END.date()
    assert len(origins) == 37
    assert all(o < TEST_END for o in origins)


def test_full_period_evaluation_validity_flag() -> None:
    """6.2: 予定上の最新起点で全日を覆えるとき通期評価が成立。"""
    assert make_dataset(("A__KAZO",), 10, 10).full_period_evaluation_valid
    assert make_dataset(("A__KAZO",), 1, 10).full_period_evaluation_valid


def test_validate_rejects_unknown_model() -> None:
    provider = registry.create("builtin-baseline")
    result = provider.validate(
        make_dataset(("A__KAZO",)),
        ProviderConfig(provider_id="builtin-baseline", model="not_exists"),
    )
    assert not result.ok
    assert any(i.code == "BASELINE_UNKNOWN_MODEL" for i in result.issues)


def test_validate_warns_when_full_period_eval_not_applicable() -> None:
    provider = registry.create("builtin-baseline")
    result = provider.validate(
        make_dataset(("A__KAZO",), origin_interval_days=20),
        ProviderConfig(provider_id="builtin-baseline", model="seasonal_naive_7"),
    )
    assert result.ok  # blocking ではない
    assert any(i.code == "FULL_PERIOD_EVAL_NOT_APPLICABLE" for i in result.issues)


def test_output_satisfies_contract() -> None:
    """適合試験4: 1回の呼び出しで horizon 1〜15 を出力できる。"""
    data = make_series(["A__KAZO", "B__KOBE"], "2024-01-01", 900)
    out = run_once(data, pd.Timestamp("2026-01-10"))
    validate_predict_frame(out)
    assert set(out["horizon"].unique()) == set(HORIZONS)
    assert sorted(out["quantile"].dropna().unique()) == [0.025, 0.1, 0.5, 0.9, 0.975]
    assert (out["yhat"] >= 0).all()


def test_yhat_is_clipped_raw() -> None:
    """7.4: yhat = max(0, yhat_raw)。原値も保存される。"""
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    out = run_once(data, pd.Timestamp("2026-01-10"))
    assert (out["yhat"] == out["yhat_raw"].clip(lower=0)).all()
    assert "yhat_raw" in out.columns


def test_intervals_are_ordered() -> None:
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    out = run_once(data, pd.Timestamp("2026-01-10"))
    pivot = out.pivot_table(
        index=["unique_id", "target_date", "horizon"],
        columns="quantile",
        values="yhat_raw",
    )
    assert (pivot[0.025] <= pivot[0.1]).all()
    assert (pivot[0.1] <= pivot[0.5]).all()
    assert (pivot[0.5] <= pivot[0.9]).all()
    assert (pivot[0.9] <= pivot[0.975]).all()


def test_context_refresh_changes_forecast() -> None:
    """適合試験2: パラメータを変えずに、起点以前の新しい実績が反映される。

    同一の ModelRef から2つの起点でコンテキストを更新し、
    予測が異なることを確認する。同じなら履歴が反映されていない。
    """
    data = make_series(["A__KAZO"], "2024-01-01", 900, seed=5)
    provider = registry.create("builtin-baseline")
    ctx = make_context()
    config = ProviderConfig(
        provider_id="builtin-baseline",
        model="moving_average_28",
        interval_levels=INTERVAL_LEVELS,
    )
    model_ref = provider.fit_parameters(
        data[data["ds"] <= TRAIN_END], make_dataset(("A__KAZO",)), config, ctx
    )

    outs = []
    for origin in (pd.Timestamp("2026-01-10"), pd.Timestamp("2026-03-10")):
        cref = provider.refresh_context(model_ref, data[data["ds"] <= origin], origin.date(), ctx)
        assert cref.model_id == model_ref.model_id  # 同一パラメータ
        outs.append(
            provider.predict(model_ref, cref, make_future(["A__KAZO"], origin, [10]), [10], ctx)[
                "yhat"
            ].iloc[0]
        )
    assert outs[0] != outs[1], "コンテキスト更新が予測へ反映されていません"


def test_no_future_leakage() -> None:
    """適合試験3 / AC-07: 起点以降の実績を変えても予測が変わらない。"""
    origin = pd.Timestamp("2026-06-01")
    base = make_series(["A__KAZO", "B__KOBE"], "2024-01-01", 900, seed=1)

    altered = base.copy()
    mask = altered["ds"] > origin
    altered.loc[mask, "y"] = altered.loc[mask, "y"] * 10 + 9999

    pd.testing.assert_frame_equal(run_once(base, origin), run_once(altered, origin))


def test_refresh_context_rejects_future_history() -> None:
    """呼出側の切り詰め漏れをプロバイダー側でも検出する。"""
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    provider = registry.create("builtin-baseline")
    ctx = make_context()
    config = ProviderConfig(provider_id="builtin-baseline", model="seasonal_naive_7")
    model_ref = provider.fit_parameters(
        data[data["ds"] <= TRAIN_END], make_dataset(("A__KAZO",)), config, ctx
    )
    origin = pd.Timestamp("2026-03-01")
    try:
        provider.refresh_context(model_ref, data, origin.date(), ctx)  # 未切り詰め
    except ContractViolationError:
        return
    raise AssertionError("起点より後を含む履歴が拒否されていません")


def test_predict_rejects_actuals_in_future_frame() -> None:
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    provider = registry.create("builtin-baseline")
    ctx = make_context()
    config = ProviderConfig(provider_id="builtin-baseline", model="seasonal_naive_7")
    origin = pd.Timestamp("2026-03-01")
    model_ref = provider.fit_parameters(
        data[data["ds"] <= TRAIN_END], make_dataset(("A__KAZO",)), config, ctx
    )
    cref = provider.refresh_context(model_ref, data[data["ds"] <= origin], origin.date(), ctx)
    future = make_future(["A__KAZO"], origin, [10])
    future["y"] = 1.0
    try:
        provider.predict(model_ref, cref, future, [10], ctx)
    except ContractViolationError:
        return
    raise AssertionError("実績列を含む future_df が拒否されていません")


def test_predict_rejects_mismatched_context() -> None:
    """context_ref の起点と future_df の起点が食い違う場合を拒否する。"""
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    provider = registry.create("builtin-baseline")
    ctx = make_context()
    config = ProviderConfig(provider_id="builtin-baseline", model="seasonal_naive_7")
    origin = pd.Timestamp("2026-03-01")
    model_ref = provider.fit_parameters(
        data[data["ds"] <= TRAIN_END], make_dataset(("A__KAZO",)), config, ctx
    )
    cref = provider.refresh_context(model_ref, data[data["ds"] <= origin], origin.date(), ctx)
    future = make_future(["A__KAZO"], origin + pd.Timedelta(days=30), [10])
    try:
        provider.predict(model_ref, cref, future, [10], ctx)
    except ContractViolationError:
        return
    raise AssertionError("起点不一致の future_df が拒否されていません")


def test_missing_days_are_not_treated_as_zero() -> None:
    """12章: 欠損（NaN）を0として扱わない。"""
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    origin = pd.Timestamp("2026-03-04")
    data.loc[data["ds"] == origin, "y"] = np.nan
    out = run_once(data, origin, model="seasonal_naive_7")
    h7 = out[(out["horizon"] == 7) & (out["forecast_kind"] == "POINT")]
    assert len(h7) == 1
    assert h7["yhat"].iloc[0] > 0, "欠落日が0として扱われています"


def test_zero_demand_series_is_handled() -> None:
    """9.1: 全期間0の系列でも例外なく0を返す。"""
    dates = pd.date_range("2024-01-01", periods=900, freq="D")
    data = pd.DataFrame({"unique_id": "Z__KOBE", "ds": dates, "y": 0.0})
    out = run_once(data, pd.Timestamp("2026-01-10"), model="moving_average_28")
    validate_predict_frame(out)
    assert (out["yhat"] == 0).all()


def test_reproducibility() -> None:
    """同一条件で完全一致すること。決定論的なため seed に依存しない。"""
    data = make_series(["A__KAZO", "B__KOBE"], "2024-01-01", 900, seed=3)
    origin = pd.Timestamp("2026-05-01")
    first = run_once(data, origin, seed=42)
    pd.testing.assert_frame_equal(first, run_once(data, origin, seed=42))
    pd.testing.assert_frame_equal(first, run_once(data, origin, seed=7))


def test_all_models_run() -> None:
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    origin = pd.Timestamp("2026-05-01")
    for model in (
        "seasonal_naive_7",
        "moving_average_28",
        "same_weekday_mean_4",
        "seasonal_naive_364",
    ):
        out = run_once(data, origin, model=model)
        validate_predict_frame(out)
        assert not out.empty, f"{model} が結果を返していません"


def test_short_history_series_excluded_without_failing_run() -> None:
    """短期履歴の系列は除外し、run全体は継続する。"""
    long_ = make_series(["A__KAZO"], "2024-01-01", 900)
    short = make_series(["NEW__KOBE"], "2025-12-20", 200)
    data = pd.concat([long_, short], ignore_index=True)
    out = run_once(data, pd.Timestamp("2026-05-01"), model="moving_average_28")
    assert "A__KAZO" in set(out["unique_id"])
    assert "NEW__KOBE" not in set(out["unique_id"])


# ---------------------------------------------------------------------------
# v2.2で追加した反例・境界テスト
# ---------------------------------------------------------------------------


def assert_raises(exc_type, fn) -> None:
    try:
        fn()
    except exc_type:
        return
    raise AssertionError(f"{exc_type.__name__} が発生しませんでした")


def test_dataset_rejects_invalid_invariants() -> None:
    base = {
        "dataset_snapshot_id": "dss_test",
        "selection_version": "sel_test",
        "unique_ids": ("A__KAZO",),
        "train_start": date(2024, 1, 1),
        "train_end": date(2025, 12, 31),
        "test_start": date(2026, 1, 1),
        "test_end": date(2026, 12, 31),
        "origin_interval_days": 10,
        "max_horizon": 15,
        "primary_horizon_max": 10,
    }

    invalid = [
        {"origin_interval_days": 0},
        {"origin_interval_days": -1},
        {"max_horizon": 0},
        {"primary_horizon_max": 0},
        {"primary_horizon_max": 16},
        {"train_start": date(2026, 1, 1)},
        {"test_start": date(2027, 1, 1)},
        {"train_end": date(2026, 1, 1)},
        {"report_horizons": (7, 16)},
        {"unique_ids": ()},
    ]
    for changes in invalid:
        args = {**base, **changes}
        assert_raises(ValueError, lambda args=args: ForecastDataset(**args))


def test_dataset_rejects_gap_between_train_and_test() -> None:
    assert_raises(
        ValueError,
        lambda: ForecastDataset(
            dataset_snapshot_id="dss_test",
            selection_version="sel_test",
            unique_ids=("A__KAZO",),
            train_start=date(2025, 1, 1),
            train_end=date(2026, 1, 10),
            test_start=date(2026, 2, 1),
            test_end=date(2026, 3, 31),
            origin_interval_days=10,
            max_horizon=15,
            primary_horizon_max=10,
        ),
    )


def test_model_metadata_is_model_specific() -> None:
    meta = registry.create("builtin-baseline").metadata()
    expected = {
        "seasonal_naive_7": 7,
        "moving_average_28": 28,
        "same_weekday_mean_4": 28,
        "seasonal_naive_364": 364,
    }
    assert {m.model_id: m.min_history_days for m in meta.models} == expected


def test_validate_rejects_provider_id_mismatch() -> None:
    provider = registry.create("builtin-baseline")
    result = provider.validate(
        make_dataset(("A__KAZO",)),
        ProviderConfig(provider_id="wrong-provider", model="seasonal_naive_7"),
    )
    assert not result.ok
    assert any(i.code == "PROVIDER_ID_MISMATCH" for i in result.issues)


def test_fit_rejects_provider_id_mismatch() -> None:
    provider = registry.create("builtin-baseline")
    data = make_series(["A__KAZO"], "2024-01-01", 730)
    config = ProviderConfig(provider_id="wrong-provider", model="seasonal_naive_7")
    assert_raises(
        ContractViolationError,
        lambda: provider.fit_parameters(
            data[data["ds"] <= TRAIN_END], make_dataset(("A__KAZO",)), config, make_context()
        ),
    )


def test_fit_rejects_test_period_rows() -> None:
    provider = registry.create("builtin-baseline")
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    config = ProviderConfig(provider_id="builtin-baseline", model="seasonal_naive_7")
    leaked = data[data["ds"] <= pd.Timestamp("2026-01-03")]
    assert_raises(
        ContractViolationError,
        lambda: provider.fit_parameters(leaked, make_dataset(("A__KAZO",)), config, make_context()),
    )


def test_model_ref_provider_identity_is_checked() -> None:
    provider = registry.create("builtin-baseline")
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    config = ProviderConfig(provider_id="builtin-baseline", model="seasonal_naive_7")
    ctx = make_context()
    model_ref = provider.fit_parameters(
        data[data["ds"] <= TRAIN_END], make_dataset(("A__KAZO",)), config, ctx
    )
    bad_ref = replace(model_ref, provider_id="other-provider")
    origin = pd.Timestamp("2026-03-01")
    assert_raises(
        ContractViolationError,
        lambda: provider.refresh_context(bad_ref, data[data["ds"] <= origin], origin.date(), ctx),
    )


def test_train_frame_contract_rejects_bad_types_and_values() -> None:
    valid = pd.DataFrame(
        {
            "unique_id": ["A"],
            "ds": pd.to_datetime(["2026-01-01"]),
            "y": [1.0],
        }
    )
    validate_train_frame(valid)

    bad_uid = valid.copy()
    bad_uid["unique_id"] = [123]
    assert_raises(ContractViolationError, lambda: validate_train_frame(bad_uid))

    null_uid = valid.copy()
    null_uid["unique_id"] = [None]
    assert_raises(ContractViolationError, lambda: validate_train_frame(null_uid))

    nat_ds = valid.copy()
    nat_ds["ds"] = pd.to_datetime([None])
    assert_raises(ContractViolationError, lambda: validate_train_frame(nat_ds))

    tz_ds = valid.copy()
    tz_ds["ds"] = pd.to_datetime(["2026-01-01"], utc=True)
    assert_raises(ContractViolationError, lambda: validate_train_frame(tz_ds))

    bool_y = valid.copy()
    bool_y["y"] = [True]
    assert_raises(ContractViolationError, lambda: validate_train_frame(bool_y))

    inf_y = valid.copy()
    inf_y["y"] = [np.inf]
    assert_raises(ContractViolationError, lambda: validate_train_frame(inf_y))

    nan_y = valid.copy()
    nan_y["y"] = [np.nan]
    validate_train_frame(nan_y)


def make_valid_predict_frame() -> pd.DataFrame:
    origin = pd.Timestamp("2026-01-01")
    rows = []
    for q, raw in [(0.1, 8.0), (0.5, 10.0), (0.9, 12.0)]:
        rows.append(
            {
                "unique_id": "A",
                "origin_date": origin,
                "target_date": origin + pd.Timedelta(days=1),
                "horizon": 1,
                "quantile": q,
                "yhat_raw": raw,
                "yhat": max(0.0, raw),
            }
        )
    for row in rows:
        row["forecast_kind"] = "QUANTILE"
    rows.append({**rows[1], "forecast_kind": "POINT", "quantile": np.nan})
    return pd.DataFrame(rows)


def test_predict_frame_requires_every_expected_quantile_per_target() -> None:
    valid = make_valid_predict_frame()
    validate_predict_frame(valid, expected_quantiles={0.1, 0.5, 0.9})

    missing = valid[valid["quantile"] != 0.1].copy()
    assert_raises(
        ContractViolationError,
        lambda: validate_predict_frame(missing, expected_quantiles={0.1, 0.5, 0.9}),
    )

    extra = pd.concat(
        [
            valid,
            pd.DataFrame(
                [
                    {
                        **valid.iloc[-1].to_dict(),
                        "quantile": 0.95,
                        "yhat_raw": 13.0,
                        "yhat": 13.0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    assert_raises(
        ContractViolationError,
        lambda: validate_predict_frame(extra, expected_quantiles={0.1, 0.5, 0.9}),
    )


def test_predict_frame_rejects_quantile_crossing() -> None:
    frame = make_valid_predict_frame()
    frame.loc[frame["quantile"] == 0.1, ["yhat_raw", "yhat"]] = 11.0
    assert_raises(ContractViolationError, lambda: validate_predict_frame(frame))


def test_predict_frame_rejects_invalid_horizon_and_nonfinite_values() -> None:
    frame = make_valid_predict_frame()
    bad_h = frame.copy()
    bad_h["horizon"] = 0
    assert_raises(ContractViolationError, lambda: validate_predict_frame(bad_h))

    bad_value = frame.copy()
    bad_value.loc[0, "yhat_raw"] = np.inf
    bad_value.loc[0, "yhat"] = np.inf
    assert_raises(ContractViolationError, lambda: validate_predict_frame(bad_value))


def test_predict_frame_rejects_timezone_aware_dates() -> None:
    frame = make_valid_predict_frame()
    frame["origin_date"] = frame["origin_date"].dt.tz_localize("UTC")
    frame["target_date"] = frame["target_date"].dt.tz_localize("UTC")
    assert_raises(ContractViolationError, lambda: validate_predict_frame(frame))


def test_intervals_are_ordered_for_deterministic_upward_trend() -> None:
    dates = pd.date_range("2024-01-01", periods=900, freq="D")
    data = pd.DataFrame({"unique_id": "A__KAZO", "ds": dates, "y": 100.0 + np.arange(900)})
    out = run_once(data, pd.Timestamp("2026-01-10"))
    validate_predict_frame(out, expected_quantiles={0.025, 0.1, 0.5, 0.9, 0.975})


def test_intervals_are_ordered_for_deterministic_downward_trend() -> None:
    dates = pd.date_range("2024-01-01", periods=900, freq="D")
    data = pd.DataFrame({"unique_id": "A__KAZO", "ds": dates, "y": 2000.0 - np.arange(900)})
    out = run_once(data, pd.Timestamp("2026-01-10"))
    validate_predict_frame(out, expected_quantiles={0.025, 0.1, 0.5, 0.9, 0.975})


# ---------------------------------------------------------------------------
# v2.3 追加分
# ---------------------------------------------------------------------------


def test_refresh_context_rejects_series_outside_dataset() -> None:
    """dataset.unique_ids にない系列は黙って落とさず、明示的に失敗させる。

    fit_parameters は dataset 外の系列を拒否するのに refresh_context が
    無視すると、実行基盤の系列取り違えが欠測件数に紛れて発見できない。
    """
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    provider = registry.create("builtin-baseline")
    ctx = make_context()
    config = ProviderConfig(
        provider_id="builtin-baseline",
        model="seasonal_naive_7",
        interval_levels=INTERVAL_LEVELS,
    )
    dataset = make_dataset(("A__KAZO",))
    model_ref = provider.fit_parameters(data[data["ds"] <= TRAIN_END], dataset, config, ctx)

    origin = pd.Timestamp("2026-03-01")
    intruder = make_series(["X__UNKNOWN"], "2024-01-01", 900)
    history = pd.concat([data, intruder], ignore_index=True)
    assert_raises(
        ContractViolationError,
        lambda: provider.refresh_context(
            model_ref, history[history["ds"] <= origin], origin.date(), ctx
        ),
    )


def test_refresh_context_silently_skips_excluded_series() -> None:
    """最小履歴不足で除外された系列は、正常な欠測として黙って除く。

    dataset には存在するため契約違反ではない。前テストの未知系列と
    区別されることを確認する。
    """
    long_ = make_series(["A__KAZO"], "2024-01-01", 900)
    short = make_series(["NEW__KOBE"], "2025-12-20", 200)
    data = pd.concat([long_, short], ignore_index=True)

    provider = registry.create("builtin-baseline")
    ctx = make_context()
    config = ProviderConfig(
        provider_id="builtin-baseline",
        model="moving_average_28",
        interval_levels=INTERVAL_LEVELS,
    )
    dataset = make_dataset(("A__KAZO", "NEW__KOBE"))
    model_ref = provider.fit_parameters(data[data["ds"] <= TRAIN_END], dataset, config, ctx)
    assert "NEW__KOBE" in model_ref.state["excluded_unique_ids"]

    origin = pd.Timestamp("2026-05-01")
    context_ref = provider.refresh_context(
        model_ref, data[data["ds"] <= origin], origin.date(), ctx
    )
    assert set(context_ref.state["series"]) == {"A__KAZO"}


def test_quantile_precision_matches_ddl() -> None:
    """quantile の丸め桁数が forecast_values.quantile の NUMERIC(8,6) と整合する。

    6桁へ丸めると値域を外れる区間水準は、DB到達前に拒否する。
    """
    assert quantiles_from_interval_levels((0.8,)) == [0.1, 0.5, 0.9]
    assert quantiles_from_interval_levels((0.95,)) == [0.025, 0.5, 0.975]
    assert quantiles_from_interval_levels((0.998,)) == [0.001, 0.5, 0.999]

    for level in (0.999999, 0.9999999):
        # 6桁では上端が 1.000 となり CHECK (quantile < 1) に抵触する
        assert_raises(
            ContractViolationError, lambda level=level: quantiles_from_interval_levels((level,))
        )


def test_full_period_evaluation_profile_distinguishes_stages() -> None:
    """被覆が成立していても、意味の異なる通期評価は比較不可と判定する。

    (10,10) は1〜10日先の混合、(1,1) は1日先のみ。どちらも全対象日を
    1回ずつ被覆するが、同一ランキングへ並べてはならない。
    """
    stage_d = make_dataset(("A__KAZO",), origin_interval_days=10, primary_horizon_max=10)
    stage_e1_same_horizon = make_dataset(
        ("A__KAZO",), origin_interval_days=1, primary_horizon_max=1
    )
    stage_e1_mixed = make_dataset(("A__KAZO",), origin_interval_days=1, primary_horizon_max=10)

    # 被覆はどちらも成立する
    assert stage_d.full_period_evaluation_valid
    assert stage_e1_same_horizon.full_period_evaluation_valid
    # だが評価プロファイルが異なるため比較できない
    assert stage_d.evaluation_profile == (10, 10)
    assert stage_e1_same_horizon.evaluation_profile == (1, 1)
    assert not stage_d.full_period_comparable_with(stage_e1_same_horizon)
    assert stage_d.full_period_comparable_with(make_dataset(("A__KAZO",)))

    # 被覆は成立してもprofileが異なる設定は比較不可
    assert stage_e1_mixed.full_period_evaluation_valid
    assert not stage_d.full_period_comparable_with(stage_e1_mixed)


# ---------------------------------------------------------------------------
# v2.4 追加分
# ---------------------------------------------------------------------------


def test_dataset_rejects_non_integer_schedule_values() -> None:
    """日数・horizonへbool/floatが混入して後段で壊れることを防ぐ。"""
    base = make_dataset(("A__KAZO",))
    for field, value in (
        ("origin_interval_days", True),
        ("origin_interval_days", 1.5),
        ("max_horizon", True),
        ("max_horizon", 15.5),
        ("primary_horizon_max", True),
        ("primary_horizon_max", 10.5),
        ("report_horizons", (7, 10.5, 15)),
    ):
        assert_raises(ValueError, lambda field=field, value=value: replace(base, **{field: value}))


def test_interval_levels_reject_invalid_types() -> None:
    """不正型はTypeErrorを漏らさず契約違反へ正規化する。"""
    for levels in (("0.8",), (None,), (True,)):
        assert_raises(
            ContractViolationError,
            lambda levels=levels: quantiles_from_interval_levels(levels),
        )


def test_interval_levels_reject_duplicates_after_rounding() -> None:
    """DDL精度で同じ端点へ潰れる複数区間を黙って統合しない。"""
    assert_raises(
        ContractViolationError,
        lambda: quantiles_from_interval_levels((0.8, 0.8)),
    )
    assert_raises(
        ContractViolationError,
        lambda: quantiles_from_interval_levels((0.8, 0.8000001)),
    )


def test_predict_rejects_series_outside_dataset() -> None:
    """future_dfの未知系列を0行として黙って落とさない。"""
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    provider = registry.create("builtin-baseline")
    ctx = make_context()
    config = ProviderConfig(
        provider_id="builtin-baseline",
        model="seasonal_naive_7",
        interval_levels=INTERVAL_LEVELS,
    )
    dataset = make_dataset(("A__KAZO",))
    model_ref = provider.fit_parameters(data[data["ds"] <= TRAIN_END], dataset, config, ctx)
    origin = pd.Timestamp("2026-03-01")
    context_ref = provider.refresh_context(
        model_ref, data[data["ds"] <= origin], origin.date(), ctx
    )
    future = make_future(["X__UNKNOWN"], origin, [1])
    assert_raises(
        ContractViolationError,
        lambda: provider.predict(model_ref, context_ref, future, [1], ctx),
    )


def test_full_period_comparison_requires_same_evaluation_scope() -> None:
    """同じprofileでも別期間・別系列・別snapshotの評価を同一ランキングへ混ぜない。"""
    base = make_dataset(("A__KAZO",))
    assert base.full_period_comparable_with(make_dataset(("A__KAZO",)))
    assert not base.full_period_comparable_with(make_dataset(("B__KOBE",)))
    assert not base.full_period_comparable_with(replace(base, dataset_snapshot_id="other"))
    shifted = ForecastDataset(
        dataset_snapshot_id=base.dataset_snapshot_id,
        selection_version=base.selection_version,
        unique_ids=base.unique_ids,
        train_start=date(2023, 1, 1),
        train_end=date(2024, 12, 31),
        test_start=date(2025, 1, 1),
        test_end=date(2025, 12, 31),
        origin_interval_days=base.origin_interval_days,
        max_horizon=base.max_horizon,
        primary_horizon_max=base.primary_horizon_max,
        report_horizons=base.report_horizons,
    )
    assert shifted.full_period_evaluation_valid
    assert shifted.evaluation_profile == base.evaluation_profile
    assert not base.full_period_comparable_with(shifted)


# ---------------------------------------------------------------------------
# v2.5 追加分
# ---------------------------------------------------------------------------


def test_predict_rejects_horizon_beyond_dataset_max() -> None:
    """モデルの対応範囲内でも、実験定義の max_horizon は超えられない。

    超えると forecast_values に実験定義外のhorizonが混入する。
    ModelMetadata.supported_horizons は (1, 400) のため、モデル側の
    検証だけでは止まらない。
    """
    data = make_series(["A__KAZO"], "2024-01-01", 900)
    provider = registry.create("builtin-baseline")
    ctx = make_context()
    config = ProviderConfig(
        provider_id="builtin-baseline",
        model="seasonal_naive_7",
        interval_levels=INTERVAL_LEVELS,
    )
    dataset = make_dataset(("A__KAZO",))  # max_horizon = 15
    model_ref = provider.fit_parameters(data[data["ds"] <= TRAIN_END], dataset, config, ctx)
    origin = pd.Timestamp("2026-03-01")
    context_ref = provider.refresh_context(
        model_ref, data[data["ds"] <= origin], origin.date(), ctx
    )

    # horizons 引数で超過
    assert_raises(
        ContractViolationError,
        lambda: provider.predict(
            model_ref, context_ref, make_future(["A__KAZO"], origin, [90]), [90], ctx
        ),
    )
    # future_df 側だけで超過
    assert_raises(
        ContractViolationError,
        lambda: provider.predict(
            model_ref,
            context_ref,
            make_future(["A__KAZO"], origin, [10, 90]),
            [10],
            ctx,
        ),
    )
    # 範囲内は通る
    out = provider.predict(
        model_ref, context_ref, make_future(["A__KAZO"], origin, [15]), [15], ctx
    )
    assert not out.empty


def test_dataset_accepts_db_derived_numeric_and_date_types() -> None:
    """DB・CSV由来の numpy 整数と pandas.Timestamp を弾かない。

    実験定義をDBから復元すると整数は numpy.int64、日付は Timestamp になる。
    bool だけを拒否し、それ以外は標準型へ正規化して保持する。
    """
    dataset = ForecastDataset(
        dataset_snapshot_id="dss_test",
        selection_version="sel_test",
        unique_ids=("A__KAZO",),
        train_start=pd.Timestamp("2024-01-01"),
        train_end=pd.Timestamp("2025-12-31"),
        test_start=pd.Timestamp("2026-01-01"),
        test_end=pd.Timestamp("2026-12-31"),
        origin_interval_days=np.int64(10),
        max_horizon=np.int32(15),
        primary_horizon_max=np.int64(10),
        report_horizons=(np.int64(7), np.int64(10), np.int64(15)),
    )
    # 正規化されて標準型で保持される
    assert isinstance(dataset.origin_interval_days, int)
    assert not isinstance(dataset.origin_interval_days, np.integer)
    assert isinstance(dataset.train_end, date)
    assert not isinstance(dataset.train_end, pd.Timestamp)
    assert all(isinstance(h, int) for h in dataset.report_horizons)
    # 正規化後も通常どおり動く
    assert len(dataset.origin_dates()) == 37
    assert dataset.full_period_evaluation_valid


def test_dataset_rejects_bad_numeric_and_date_types_as_value_error() -> None:
    """契約違反は ValueError に統一し、TypeError を漏らさない。"""
    base = {
        "dataset_snapshot_id": "dss_test",
        "selection_version": "sel_test",
        "unique_ids": ("A__KAZO",),
        "train_start": date(2024, 1, 1),
        "train_end": date(2025, 12, 31),
        "test_start": date(2026, 1, 1),
        "test_end": date(2026, 12, 31),
        "origin_interval_days": 10,
        "max_horizon": 15,
        "primary_horizon_max": 10,
    }
    invalid = [
        {"origin_interval_days": True},
        {"origin_interval_days": 10.0},
        {"max_horizon": "15"},
        {"report_horizons": (7, True)},
        {"train_end": "2025-12-31"},
        {"test_end": None},
    ]
    for changes in invalid:
        args = {**base, **changes}
        assert_raises(ValueError, lambda args=args: ForecastDataset(**args))


def test_interval_levels_reject_rounding_drift() -> None:
    """丸めで実現水準が変わる指定を拒否する。

    通すと実験定義には要求水準が残り、保存される予測値は別水準の区間になる。
    Coverage がどの水準に対する被覆か判別できなくなる。
    """
    for level in (0.8, 0.9, 0.95, 0.99, 0.998):
        qs = quantiles_from_interval_levels((level,))
        assert round(qs[-1] - qs[0], 6) == level

    for level in (0.9985005, 0.9976003):
        assert_raises(
            ContractViolationError,
            lambda level=level: quantiles_from_interval_levels((level,)),
        )


def test_horizon_comparison_requires_matching_origin_keys() -> None:
    """horizon別評価も予定起点の一致が必要。異なる起点は共通キー抽出後に比較する。

    仕様書10章「段階間の比較には同一条件のhorizon別評価を用いる」に対応する。
    """
    stage_d = make_dataset(("A__KAZO",), origin_interval_days=10, primary_horizon_max=10)
    stage_e1 = make_dataset(("A__KAZO",), origin_interval_days=1, primary_horizon_max=10)

    # 起点集合が違うため、そのままのhorizon別比較も拒否する
    assert not stage_d.full_period_comparable_with(stage_e1)
    assert not stage_d.horizon_comparable_with(stage_e1)

    # 母集団が違えばhorizon別でも比較できない
    other_population = make_dataset(("A__KAZO", "B__KOBE"))
    assert not stage_d.horizon_comparable_with(other_population)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {fn.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
