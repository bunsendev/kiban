"""MLForecast Ridge Providerの固定学習・未来非参照・保存契約。"""

from __future__ import annotations

import copy
import logging
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("mlforecast")

from forecast_provider.artifacts import ForecastArtifactRepository, LocalArtifactStore
from forecast_provider.artifacts.contracts import ArtifactError
from forecast_provider.contracts import ForecastDataset, ProviderConfig, RunContext
from forecast_provider.errors import ContractViolationError, NonRetryableProviderError
from forecast_provider.evaluation import compare_runs
from forecast_provider.frames import validate_predict_frame
from forecast_provider.providers.causal_series import prepare_daily_series
from forecast_provider.providers.mlforecast_codec import MLForecastRidgeCodec
from forecast_provider.providers.mlforecast_state import (
    LAGS,
    fit_ridge,
    predict_ridge,
)
from forecast_provider.registry import registry
from forecast_provider.run_context import cutoff_for_origin
from forecast_provider.runner import run_fixed_provider

TRAIN_END = date(2024, 4, 30)


def make_dataset() -> ForecastDataset:
    return ForecastDataset(
        dataset_snapshot_id="dss-mlforecast",
        selection_version="sel-mlforecast",
        unique_ids=("A", "B"),
        train_start=date(2024, 1, 1),
        train_end=TRAIN_END,
        test_start=date(2024, 5, 1),
        test_end=date(2024, 5, 15),
        origin_interval_days=15,
        max_horizon=15,
        primary_horizon_max=15,
        report_horizons=(1, 7, 15),
    )


def make_config() -> ProviderConfig:
    return ProviderConfig(
        "mlforecast-ridge",
        "ridge_lag_calendar",
        {"alpha": 1.0},
        (),
        preprocessing_version="mlforecast-causal-ffill-lags-dow-v1",
    )


def make_context(tmp_path, origin: date = TRAIN_END) -> RunContext:
    return RunContext(
        "run-mlforecast",
        "exp-mlforecast",
        7,
        datetime.now(UTC) + timedelta(hours=1),
        tmp_path,
        tmp_path,
        "cpu-small",
        logging.getLogger("mlforecast-test"),
        availability_mode="ASSUMED",
        cutoff_at=cutoff_for_origin(origin),
        origin_date=origin,
    )


def make_data(end: str = "2024-05-15") -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", end, freq="D")
    weekly = np.asarray([3.0, 7.0, 11.0, 5.0, 13.0, 2.0, 0.0])
    frames = []
    for offset, uid in enumerate(("A", "B")):
        y = 20.0 + offset * 5 + weekly[dates.dayofweek] + np.arange(len(dates)) * 0.03
        frames.append(pd.DataFrame({"unique_id": uid, "ds": dates, "y": y}))
    return pd.concat(frames, ignore_index=True)


def make_future(origin: date, horizons=range(1, 16)) -> pd.DataFrame:
    timestamp = pd.Timestamp(origin)
    return pd.DataFrame(
        [
            {
                "unique_id": uid,
                "origin_date": timestamp,
                "target_date": timestamp + pd.Timedelta(days=h),
                "horizon": h,
            }
            for uid in ("A", "B")
            for h in horizons
        ]
    )


def fitted(tmp_path):
    provider = registry.create("mlforecast-ridge")
    dataset, config = make_dataset(), make_config()
    context, data = make_context(tmp_path), make_data()
    train = data[data.ds.le(pd.Timestamp(TRAIN_END))]
    model = provider.fit_parameters(train, dataset, config, context)
    return provider, dataset, config, context, data, model


def test_metadata_registry_and_explicit_configuration(tmp_path) -> None:
    provider = registry.create("mlforecast-ridge")
    metadata = provider.metadata()
    assert metadata.library_name == "mlforecast"
    assert metadata.library_version == "1.1.0"
    assert metadata.category == "機械学習"
    assert metadata.capabilities.license == "Apache-2.0"
    assert metadata.capabilities.eligible_for_primary_ranking
    assert provider.validate(make_dataset(), make_config()).ok

    bad = ProviderConfig(
        "mlforecast-ridge",
        "ridge_lag_calendar",
        {"alpha": 2.0},
        (),
        preprocessing_version="mlforecast-causal-ffill-lags-dow-v1",
    )
    assert not provider.validate(make_dataset(), bad).ok
    with pytest.raises(ContractViolationError):
        provider.fit_parameters(make_data(), make_dataset(), bad, make_context(tmp_path))


def test_causal_fill_and_recursive_prediction_match_mlforecast() -> None:
    from mlforecast import MLForecast
    from sklearn.linear_model import Ridge

    source = pd.DataFrame(
        {
            "unique_id": "A",
            "ds": pd.date_range("2024-01-01", periods=90),
            "y": [np.nan, 0.0, np.nan, *np.arange(87, dtype=float)],
        }
    )
    series, actual, imputed = prepare_daily_series(
        source, date(2024, 1, 1), date(2024, 3, 30)
    )
    assert series.iloc[:3].tolist() == [0.0, 0.0, 0.0]
    assert actual == 88 and imputed == 1
    state = fit_ridge(series, 1.0)
    actual_prediction = predict_ridge(state, series, 8)

    frame = pd.DataFrame({"unique_id": "A", "ds": series.index, "y": series.to_numpy()})
    native = MLForecast(
        models={"ridge": Ridge(alpha=1.0, solver="cholesky")},
        freq="D",
        lags=list(LAGS),
        date_features=["dayofweek"],
    ).fit(frame, static_features=[])
    assert np.allclose(actual_prediction, native.predict(8)["ridge"].to_numpy())


def test_library_fit_failure_is_not_short_history(tmp_path, monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("library failure")

    monkeypatch.setattr("forecast_provider.providers.mlforecast_ridge.fit_ridge", fail)
    provider = registry.create("mlforecast-ridge")
    train = make_data()
    train = train[train.ds.le(pd.Timestamp(TRAIN_END))]
    with pytest.raises(NonRetryableProviderError, match="学習が全対象で失敗"):
        provider.fit_parameters(train, make_dataset(), make_config(), make_context(tmp_path))


def test_fixed_parameters_refresh_and_future_actuals_are_not_read(tmp_path) -> None:
    provider, _, _, context, data, model = fitted(tmp_path)
    signatures = copy.deepcopy(model.state["parameter_signatures"])
    history = data[data.ds.le(pd.Timestamp(TRAIN_END))]
    ref = provider.refresh_context(model, history, TRAIN_END, context)
    expected = provider.predict(model, ref, make_future(TRAIN_END), list(range(1, 16)), context)
    validate_predict_frame(expected, expected_targets=make_future(TRAIN_END))

    altered = data.copy()
    altered.loc[altered.ds.gt(pd.Timestamp(TRAIN_END)), "y"] = 999999.0
    other_ref = provider.refresh_context(
        model, altered[altered.ds.le(pd.Timestamp(TRAIN_END))], TRAIN_END, context
    )
    actual = provider.predict(model, other_ref, make_future(TRAIN_END), list(range(1, 16)), context)
    pd.testing.assert_frame_equal(expected, actual)
    assert model.state["parameter_signatures"] == signatures
    with pytest.raises(ContractViolationError):
        provider.predict(
            model,
            ref,
            make_future(TRAIN_END).assign(y=1.0),
            list(range(1, 16)),
            context,
        )


def test_json_artifact_roundtrip_and_signature_tamper_detection(tmp_path) -> None:
    provider, dataset, config, context, data, model = fitted(tmp_path)
    codec = MLForecastRidgeCodec()
    repository = ForecastArtifactRepository(LocalArtifactStore(tmp_path / "objects"), [codec])
    model_artifact = repository.save_model(model, dataset, config, context)
    restored_model = repository.load_model(model_artifact, dataset, config, context)
    ref = provider.refresh_context(
        restored_model, data[data.ds.le(pd.Timestamp(TRAIN_END))], TRAIN_END, context
    )
    context_artifact = repository.save_context(ref, model_artifact, dataset, config, context)
    restored_ref = repository.load_context(
        context_artifact, model_artifact, dataset, config, context
    )
    expected = provider.predict(model, ref, make_future(TRAIN_END), list(range(1, 16)), context)
    actual = provider.predict(
        restored_model, restored_ref, make_future(TRAIN_END), list(range(1, 16)), context
    )
    pd.testing.assert_frame_equal(expected, actual)
    artifact_path = tmp_path / "objects" / f"{model_artifact.sha256}.json"
    assert b"pickle" not in artifact_path.read_bytes().lower()

    payload = codec.encode_model(model, dataset, config, context)
    payload["models"]["A"]["intercept"] += 1
    with pytest.raises(ArtifactError):
        codec.decode_model(payload, model, dataset, config, context)


def test_common_runner_and_three_provider_official_comparison(tmp_path) -> None:
    data, dataset, context = make_data(), make_dataset(), make_context(tmp_path)
    ml = run_fixed_provider(
        data, dataset, make_config(), context, availability_mode="ASSUMED"
    )["predictions"]
    baseline = run_fixed_provider(
        data,
        dataset,
        ProviderConfig(
            "builtin-baseline",
            "moving_average_28",
            {},
            (),
            preprocessing_version="daily-nan-preserving-v1",
        ),
        context,
        availability_mode="ASSUMED",
    )["predictions"]
    stats = run_fixed_provider(
        data,
        dataset,
        ProviderConfig(
            "statsforecast-ets",
            "auto_ets_weekly",
            {"season_length": 7, "model": "ZZZ"},
            (),
            preprocessing_version="statsforecast-causal-ffill-v1",
        ),
        context,
        availability_mode="ASSUMED",
    )["predictions"]
    comparison = compare_runs(
        dict.fromkeys(("baseline", "autoets", "ridge"), dataset),
        {"baseline": baseline, "autoets": stats, "ridge": ml},
        data,
        truth_version="synthetic-v1",
        mode="primary",
    )
    assert comparison["official_ranking_ready"]
    assert comparison["official_runs"] == ["baseline", "autoets", "ridge"]
    assert all(score["run_success_rate"] == 1 for score in comparison["scores"].values())
