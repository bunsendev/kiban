"""4方式の予測・欠損・残差・部分系列を保存前後で比較する。"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from test_builtin_baseline import make_future

from forecast_provider.artifacts import ForecastArtifactRepository, LocalArtifactStore
from forecast_provider.providers.baseline_codec import BuiltinBaselineCodec
from forecast_provider.providers.builtin_baseline import BuiltinBaselineProvider
from forecast_provider.runner import available_history


@pytest.fixture
def artifact_case(phase1a_case, tmp_path):
    data, ds, config, parent = phase1a_case
    provider = BuiltinBaselineProvider()
    repo = ForecastArtifactRepository(LocalArtifactStore(tmp_path), [BuiltinBaselineCodec()])
    return data, ds, config, parent, provider, repo


@pytest.mark.parametrize(
    "model_name",
    ["seasonal_naive_7", "moving_average_28", "same_weekday_mean_4", "seasonal_naive_364"],
)
@pytest.mark.parametrize("mode", ["ASSUMED", "OBSERVED"])
def test_model_and_context_roundtrip_preserve_predictions(artifact_case, model_name, mode):
    data, ds, config, parent, provider, repo = artifact_case
    ds = replace(ds, availability_mode=mode)
    config = replace(config, model=model_name, interval_levels=(0.8,))
    parent = replace(parent, availability_mode=mode)
    data = data.copy()
    data.loc[data.ds.eq(pd.Timestamp("2025-12-30")), "y"] = np.nan
    data.loc[data.ds.eq(pd.Timestamp("2025-12-29")), "y"] = 0.0
    data["available_at"] = (data.ds + pd.Timedelta(days=1)).dt.tz_localize("Asia/Tokyo")
    fit = parent.for_origin(ds.train_end)
    train = available_history(data, pd.Timestamp(ds.train_end), availability_mode=mode)
    model = provider.fit_parameters(train, ds, config, fit)
    ticket = repo.save_model(model, ds, config, fit)
    assert repo.save_model(model, ds, config, fit) == ticket
    restored = repo.load_model(ticket, ds, config, fit)
    assert restored.model_id == model.model_id
    assert restored.parameter_fingerprint == model.parameter_fingerprint
    assert restored.artifact_uri == f"sha256:{ticket.sha256}"
    assert model.artifact_uri is None
    assert repo.save_model(restored, ds, config, fit) == ticket
    assert restored.state["residual_quantiles"] == model.state["residual_quantiles"]
    for uid, series in model.state["train_series"].items():
        pd.testing.assert_series_equal(
            series, restored.state["train_series"][uid], check_exact=True
        )
    for origin in ds.origin_dates():
        ctx = parent.for_origin(origin)
        history = available_history(data, pd.Timestamp(origin), availability_mode=mode)
        ref = provider.refresh_context(model, history, origin, ctx)
        context_ticket = repo.save_context(ref, ticket, ds, config, ctx)
        loaded = repo.load_context(context_ticket, ticket, ds, config, ctx)
        assert loaded.context_id == ref.context_id and loaded.cutoff_at == ref.cutoff_at
        future = make_future(ds.unique_ids, pd.Timestamp(origin), [1, 7])
        expected = provider.predict(model, ref, future, [1, 7], ctx)
        actual = provider.predict(restored, loaded, future, [1, 7], ctx)
        pd.testing.assert_frame_equal(expected, actual, check_exact=True)
        refreshed = provider.refresh_context(restored, history, origin, ctx)
        pd.testing.assert_frame_equal(
            expected, provider.predict(restored, refreshed, future, [1, 7], ctx), check_exact=True
        )


def test_excluded_and_missing_context_series_are_retained(artifact_case):
    data, ds, config, parent, provider, repo = artifact_case
    data = data.copy()
    data.loc[data.unique_id.eq("B"), "y"] = np.nan
    model = provider.fit_parameters(
        data[data.ds.le(pd.Timestamp(ds.train_end))], ds, config, parent
    )
    ticket = repo.save_model(model, ds, config, parent)
    restored = repo.load_model(ticket, ds, config, parent)
    assert restored.state["excluded_unique_ids"] == ("B",)
    # 履歴が除外系列だけの場合も、空のcontext系列を0で捏造しない。
    ref = provider.refresh_context(
        model,
        data[data.unique_id.eq("B") & data.ds.le(pd.Timestamp(ds.train_end))],
        ds.train_end,
        parent,
    )
    context_ticket = repo.save_context(ref, ticket, ds, config, parent)
    loaded = repo.load_context(context_ticket, ticket, ds, config, parent)
    assert loaded.state["series"] == {}
    future = make_future(ds.unique_ids, pd.Timestamp(ds.train_end), [1])
    assert provider.predict(restored, loaded, future, [1], parent).empty
