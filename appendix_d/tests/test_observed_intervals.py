"""OBSERVED区間残差が過去起点の利用可能時刻を再現することを固定する。"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from test_builtin_baseline import TRAIN_END, make_context, make_dataset

from forecast_provider import ProviderConfig
from forecast_provider.errors import ContractViolationError
from forecast_provider.providers.builtin_baseline import BuiltinBaselineProvider
from forecast_provider.runner import available_history, run_fixed_baseline


def _observed_data(days: int = 1100) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=days)
    frame = pd.DataFrame(
        {
            "unique_id": "A",
            "ds": dates,
            "y": 50.0 + dates.dayofweek.to_numpy() * 3 + np.sin(np.arange(days) / 11),
        }
    )
    frame["available_at"] = (frame.ds + pd.Timedelta(days=1)).dt.tz_localize("Asia/Tokyo")
    return frame


def _fit(data: pd.DataFrame, model: str = "seasonal_naive_7"):
    dataset = replace(make_dataset(("A",)), availability_mode="OBSERVED")
    config = ProviderConfig(
        "builtin-baseline",
        model,
        preprocessing_version="daily-nan-preserving-v1",
        interval_levels=(0.8,),
    )
    context = replace(make_context(), availability_mode="OBSERVED")
    train = available_history(data, TRAIN_END, availability_mode="OBSERVED")
    return BuiltinBaselineProvider().fit_parameters(train, dataset, config, context)


@pytest.mark.parametrize(
    "model",
    ["seasonal_naive_7", "moving_average_28", "same_weekday_mean_4", "seasonal_naive_364"],
)
def test_on_time_observed_residuals_match_assumed_semantics(model: str) -> None:
    data = _observed_data()
    observed = _fit(data, model).state["residual_quantiles"]["A"]
    dataset = make_dataset(("A",))
    config = ProviderConfig(
        "builtin-baseline",
        model,
        preprocessing_version="daily-nan-preserving-v1",
        interval_levels=(0.8,),
    )
    assumed = BuiltinBaselineProvider().fit_parameters(
        data[data.ds.le(TRAIN_END)], dataset, config, make_context()
    ).state["residual_quantiles"]["A"]
    assert observed.keys() == assumed.keys()
    assert observed == pytest.approx(assumed, abs=1e-12)


def test_late_history_revision_does_not_change_historical_residuals() -> None:
    original = _observed_data()
    revised = original.copy()
    first_week = revised.ds.lt(pd.Timestamp("2024-01-08"))
    revised.loc[first_week, "y"] += 100_000
    # 最初の7日間はTRAIN終了時には利用できるが、どのhistorical originでも
    # まだ利用できなかった。seasonal naiveの履歴値へ遡及してはならない。
    late = (TRAIN_END + pd.Timedelta(days=1)).tz_localize("Asia/Tokyo")
    original.loc[first_week, "available_at"] = late
    revised.loc[first_week, "available_at"] = late

    before = _fit(original).state["residual_quantiles"]["A"]
    after = _fit(revised).state["residual_quantiles"]["A"]
    assert before
    assert after == before


@pytest.mark.parametrize("invalid", ["NAIVE", "MISSING"])
def test_observed_rejects_invalid_arrival_evidence(invalid: str) -> None:
    data = _observed_data()
    if invalid == "NAIVE":
        data["available_at"] = data.available_at.dt.tz_localize(None)
    else:
        data.loc[data.index[0], "available_at"] = pd.NaT
    with pytest.raises(ContractViolationError, match="timezone付き・非欠損"):
        _fit(data)


def test_observed_run_emits_intervals_and_restores_point_contract() -> None:
    data = _observed_data()
    dataset = replace(make_dataset(("A",)), availability_mode="OBSERVED")
    config = ProviderConfig(
        "builtin-baseline",
        "moving_average_28",
        preprocessing_version="daily-nan-preserving-v1",
        interval_levels=(0.8,),
    )
    context = replace(make_context(), availability_mode="OBSERVED")
    result = run_fixed_baseline(
        data,
        dataset,
        config,
        context,
        availability_mode="OBSERVED",
    )

    assert result["status"] == "SUCCESS"
    kinds = set(result["predictions"].forecast_kind)
    assert kinds == {"POINT", "QUANTILE"}
    assert set(result["predictions"].dropna(subset=["quantile"])["quantile"]) == {0.1, 0.5, 0.9}
    assert result["ledger"].interval_status.eq("SUCCESS").all()
