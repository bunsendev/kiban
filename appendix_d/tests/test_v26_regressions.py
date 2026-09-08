"""レビューで再現した反例。入力から保存前照合・比較までを検証する。"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from test_builtin_baseline import (
    TRAIN_END,
    make_context,
    make_dataset,
    make_future,
    make_valid_predict_frame,
)

from forecast_provider import ProviderConfig, registry
from forecast_provider.errors import ContractViolationError
from forecast_provider.evaluation import (
    build_plan,
    compare_runs,
    cumulative_evaluation,
    metrics,
    primary_plan,
    reconcile_predictions,
)
from forecast_provider.frames import (
    validate_future_frame,
    validate_predict_frame,
    validate_train_frame,
)
from forecast_provider.providers.builtin_baseline import (
    _historical_forecast,
    _point_forecast,
)


def fitted(days=731, intervals=(0.8,), model="seasonal_naive_7"):
    data = pd.DataFrame(
        {
            "unique_id": "A",
            "ds": pd.date_range(end=TRAIN_END, periods=days),
            "y": np.arange(days, dtype=float),
        }
    )
    p = registry.create("builtin-baseline")
    ctx = make_context()
    ds = make_dataset(("A",))
    m = p.fit_parameters(
        data, ds, ProviderConfig("builtin-baseline", model, interval_levels=intervals), ctx
    )
    c = p.refresh_context(m, data, TRAIN_END.date(), ctx)
    return p, ctx, ds, m, c


def test_average_is_anchored_at_origin_not_last_record():
    s = pd.Series(np.arange(1, 61, dtype=float), index=pd.date_range("2025-11-02", periods=60))
    assert _point_forecast(s, pd.Timestamp("2026-01-11"), 1, "moving_average_28") == 51.5
    assert _point_forecast(s, pd.Timestamp("2026-03-01"), 1, "moving_average_28") is None


@pytest.mark.parametrize(
    "model", ["seasonal_naive_7", "same_weekday_mean_4", "moving_average_28", "seasonal_naive_364"]
)
def test_live_and_residual_rules_match_with_missing_days(model):
    values = np.arange(450, dtype=float)
    values[[12, 33, 400, 406, 407, 411, 429, 435]] = np.nan
    s = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values)))
    for h in (1, 7, 15):
        calculated = _historical_forecast(values, h, model)
        for target in (407, 413, 436, 449):
            predicted = _point_forecast(s.iloc[: target - h + 1], s.index[target], h, model)
            if predicted is None:
                assert np.isnan(calculated[target])
            else:
                assert calculated[target] == pytest.approx(predicted)


def test_point_and_median_are_separate_on_trend():
    p, ctx, _, m, c = fitted()
    out = p.predict(m, c, make_future(["A"], TRAIN_END, [1]), [1], ctx)
    validate_predict_frame(out, expected_quantiles={0.1, 0.5, 0.9})
    assert out.loc[out.forecast_kind.eq("POINT"), "yhat"].item() == 724
    assert out.loc[out.forecast_kind.eq("POINT"), "quantile"].isna().all()
    assert out.loc[out.forecast_kind.eq("QUANTILE"), "yhat"].tolist() == [731, 731, 731]


def test_insufficient_residuals_mark_intervals_unavailable():
    p, ctx, _, m, c = fitted(days=7)
    future = make_future(["A"], TRAIN_END, [1])
    out = p.predict(m, c, future, [1], ctx)
    assert out.forecast_kind.tolist() == ["POINT"]
    ledger = reconcile_predictions(future, out, expected_quantiles={0.1, 0.5, 0.9})
    assert ledger.status.item() == "SUCCESS"
    assert ledger.interval_status.item() == "UNAVAILABLE"


def test_predict_uses_cached_train_residuals(monkeypatch):
    p, ctx, _, m, c = fitted()
    original = dict(m.state["residual_quantiles"]["A"])

    def forbidden(*args, **kwargs):
        raise AssertionError("predictで残差再計算")

    monkeypatch.setattr(
        "forecast_provider.providers.builtin_baseline._residual_quantiles", forbidden
    )
    p.predict(m, c, make_future(["A"], TRAIN_END, [1]), [1], ctx)
    assert original == m.state["residual_quantiles"]["A"]


@pytest.mark.parametrize("bad", [True, 1.5, None, np.nan, "1", "x"])
def test_future_horizon_bad_type_is_contract_error(bad):
    p, ctx, _, m, c = fitted(intervals=())
    future = make_future(["A"], TRAIN_END, [1])
    future["horizon"] = bad
    with pytest.raises(ContractViolationError):
        p.predict(m, c, future, [1], ctx)


@pytest.mark.parametrize("field", ["train_start", "train_end", "test_start", "test_end"])
def test_dataset_nat_is_value_error(field):
    with pytest.raises(ValueError):
        replace(make_dataset(("A",)), **{field: pd.NaT})


@pytest.mark.parametrize("bad", [None, "7", True])
def test_bad_report_horizons_container(bad):
    with pytest.raises(ValueError):
        replace(make_dataset(("A",)), report_horizons=bad)


def test_intraday_and_negative_shipments_rejected():
    f = pd.DataFrame({"unique_id": ["A"], "ds": [pd.Timestamp("2025-01-01")], "y": [-1.0]})
    with pytest.raises(ContractViolationError):
        validate_train_frame(f)
    f["y"] = 1.0
    f["ds"] += pd.Timedelta(hours=12)
    with pytest.raises(ContractViolationError):
        validate_train_frame(f)


def test_future_date_mismatch_and_duplicates_rejected():
    f = make_future(["A"], TRAIN_END, [1])
    with pytest.raises(ContractViolationError):
        validate_future_frame(pd.concat([f, f]))
    f["target_date"] += pd.Timedelta(hours=12)
    with pytest.raises(ContractViolationError):
        validate_future_frame(f)


def test_missing_target_is_rejected_or_ledgered_not_hidden():
    p, ctx, _, m, c = fitted(intervals=())
    future = make_future(["A"], TRAIN_END, [1, 2])
    out = p.predict(m, c, future, [1, 2], ctx)
    missing = out[out.horizon.eq(1)]
    with pytest.raises(ContractViolationError):
        validate_predict_frame(missing, expected_targets=future)
    ledger = reconcile_predictions(future, missing)
    assert ledger.status.tolist() == ["SUCCESS", "FAILED"]
    assert pd.isna(ledger.yhat.iloc[1])
    with pytest.raises(ContractViolationError):
        validate_predict_frame(out.iloc[:0])
    assert reconcile_predictions(future, out.iloc[:0]).status.eq("FAILED").all()


def test_extra_prediction_rejected():
    f = make_valid_predict_frame()
    plan = f[["unique_id", "origin_date", "target_date", "horizon"]].drop_duplicates()
    plan["unique_id"] = "other"
    with pytest.raises(ContractViolationError):
        reconcile_predictions(plan, f)


def test_point_cannot_be_mislabeled_as_quantile():
    f = make_valid_predict_frame()
    f.loc[f.forecast_kind.eq("POINT"), "quantile"] = 0.5
    with pytest.raises(ContractViolationError):
        validate_predict_frame(f)


def fixture_comparison():
    ds = replace(make_dataset(("A",)), test_end=pd.Timestamp("2026-01-20"))
    other = replace(ds, origin_interval_days=1, primary_horizon_max=1)

    def perfect(plan):
        return plan.assign(forecast_kind="POINT", quantile=np.nan, yhat_raw=10.0, yhat=10.0)

    truth = pd.DataFrame(
        {"unique_id": "A", "ds": pd.date_range("2026-01-01", periods=20), "y": 10.0}
    )
    return ds, other, perfect(build_plan(ds)), perfect(build_plan(other)), truth


def test_different_schedules_align_same_origin_target_horizon():
    a, b, out_a, out_b, truth = fixture_comparison()
    assert not a.horizon_comparable_with(b)
    r = compare_runs(
        {"a": a, "b": b}, {"a": out_a, "b": out_b}, truth, truth_version="v1", horizon=7
    )
    assert r["scores"]["a"]["truth_eligible_count"] == 2
    assert r["scores"]["b"]["truth_eligible_count"] == 2
    assert r["scores"]["b"]["run_planned_count"] == 14
    assert r["ranking_ready"]
    with pytest.raises(ContractViolationError):
        compare_runs(
            {"a": a, "b": b}, {"a": out_a, "b": out_b}, truth, truth_version="v1", mode="primary"
        )


def test_failures_affect_success_rate_and_common_set():
    a, _, out, _, truth = fixture_comparison()
    damaged = out.iloc[1:]
    r = compare_runs({"a": a, "b": a}, {"a": out, "b": damaged}, truth, truth_version="v1")
    assert not r["ranking_ready"]
    assert r["scores"]["b"]["run_failure_count"] == 1
    assert not r["scores"]["b"]["official_eligible"]
    assert r["scores"]["a"]["common_success_count"] == len(out) - 1
    assert r["scores"]["a"]["common_metrics"]["mae"] == 0
    changed = compare_runs({"a": a, "b": a}, {"a": out, "b": out}, truth, truth_version="v1")
    assert changed["comparison_set_id"] != r["comparison_set_id"]
    empty = compare_runs({"a": a}, {"a": out.iloc[:0]}, truth, truth_version="v1")
    assert empty["scores"]["a"]["run_success_count"] == 0
    assert empty["scores"]["a"]["common_metrics"]["wape_pct"] is None


def test_truth_missing_is_not_counted_as_prediction_failure():
    a, _, out, _, truth = fixture_comparison()
    truth.loc[0, "y"] = np.nan
    r = compare_runs({"a": a}, {"a": out}, truth, truth_version="v1")
    assert r["scores"]["a"]["truth_missing_count"] == 1
    assert r["scores"]["a"]["run_failure_count"] == 0


def test_primary_plan_never_falls_back_to_old_success():
    a, _, out, _, _ = fixture_comparison()
    latest = primary_plan(a)
    jan11 = latest[latest.target_date.eq(pd.Timestamp("2026-01-11"))]
    assert jan11.horizon.item() == 1
    missing = out[~((out.target_date == pd.Timestamp("2026-01-11")) & (out.horizon == 1))]
    ledger = reconcile_predictions(build_plan(a), missing)
    row = jan11.merge(ledger, on=list(jan11.columns))
    assert row.status.item() == "FAILED"


def test_cumulative_requires_complete_days_and_reports_edges():
    a, _, out, _, truth = fixture_comparison()
    ledger = reconcile_predictions(build_plan(a), out)
    sums = cumulative_evaluation(ledger, truth, 15)
    assert sums.status.tolist() == ["SUCCESS", "INCOMPLETE_WINDOW"]
    assert sums.actual_sum.iloc[0] == 150
    damaged = reconcile_predictions(build_plan(a), out.iloc[1:])
    assert cumulative_evaluation(damaged, truth, 15).status.iloc[0] == "FAILED_PREDICTION"
    truth.loc[0, "y"] = np.nan
    assert cumulative_evaluation(ledger, truth, 15).status.iloc[0] == "MISSING_TRUTH"


def test_metrics_match_hand_calculation_and_zero_denominator():
    r = metrics(np.array([0, 10]), np.array([5, 5]))
    assert r == {
        "wape_pct": 100.0,
        "mae": 5.0,
        "rmse": 5.0,
        "bias": 0.0,
        "bias_rate_pct": 0.0,
        "under": 5.0,
        "over": 5.0,
    }
    assert metrics(np.array([0]), np.array([1]))["wape_pct"] is None


def test_leap_year_grid_has_546_rows_per_series():
    ds = replace(
        make_dataset(("A",)),
        train_start=pd.Timestamp("2022-01-01"),
        train_end=pd.Timestamp("2023-12-31"),
        test_start=pd.Timestamp("2024-01-01"),
        test_end=pd.Timestamp("2024-12-31"),
    )
    assert len(build_plan(ds)) == 546
    assert len(primary_plan(ds)) == 366


def test_latest_origin_policy_covers_overlapping_primary_windows():
    ds = replace(make_dataset(("A",)), origin_interval_days=1, primary_horizon_max=10)
    assert ds.full_period_evaluation_valid
    assert len(primary_plan(ds)) == 365
    assert primary_plan(ds).horizon.eq(1).all()


def test_availability_cutoff_blocks_late_arrivals():
    from forecast_provider.runner import available_history

    data = pd.DataFrame(
        {
            "unique_id": ["A", "A"],
            "ds": pd.to_datetime(["2025-12-30", "2025-12-31"]),
            "y": [1.0, 2.0],
            "available_at": pd.to_datetime(["2025-12-31T00:00+09:00", "2026-01-01T09:00+09:00"]),
        }
    )
    h = available_history(data, TRAIN_END, availability_mode="OBSERVED")
    assert len(h) == 2
    assert h.y.iloc[0] == 1.0
    assert pd.isna(h.y.iloc[1])
    assert len(available_history(data, TRAIN_END, availability_mode="ASSUMED")) == 2
    with pytest.raises(ContractViolationError):
        available_history(
            data.drop(columns="available_at"), TRAIN_END, availability_mode="OBSERVED"
        )


def test_runner_preserves_failure_ledger_and_future_invariance():
    from forecast_provider.runner import run_fixed_baseline

    ds = replace(make_dataset(("A",)), test_end=pd.Timestamp("2026-01-20"))
    data = pd.DataFrame(
        {"unique_id": "A", "ds": pd.date_range("2024-01-01", "2026-02-01"), "y": 10.0}
    )
    config = ProviderConfig("builtin-baseline", "moving_average_28")
    first = run_fixed_baseline(data, ds, config, make_context(), availability_mode="ASSUMED")
    assert first["status"] == "SUCCESS"
    assert first["fit_calls"] == 1
    data.loc[data.ds.gt(pd.Timestamp("2026-01-10")), "y"] = 99999.0
    second = run_fixed_baseline(data, ds, config, make_context(), availability_mode="ASSUMED")
    pd.testing.assert_frame_equal(first["predictions"], second["predictions"])
    # TRAIN全件が欠損の場合、結果を消さず全予定を失敗台帳に残す。
    data["y"] = np.nan
    empty = run_fixed_baseline(data, ds, config, make_context(), availability_mode="ASSUMED")
    assert empty["status"] == "FAILED"
    assert len(empty["ledger"]) == len(build_plan(ds))
    assert empty["ledger"].status.eq("FAILED").all()


def test_comparison_rejects_mixed_availability_assumptions():
    ds, _, out, _, truth = fixture_comparison()
    observed = replace(ds, availability_mode="OBSERVED")
    with pytest.raises(ContractViolationError):
        compare_runs({"a": ds, "b": observed}, {"a": out, "b": out}, truth, truth_version="v1")


def test_bias_is_total_quantity_not_mean_error():
    r = metrics(np.array([1.0, 2.0]), np.array([2.0, 3.0]))
    assert r["bias"] == 2.0
    assert r["bias_rate_pct"] == pytest.approx(200 / 3)
