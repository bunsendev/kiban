"""StatsForecast AutoETS Providerの固定学習・未来非参照・保存契約。"""

from __future__ import annotations

import copy
import logging
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("statsforecast")

from forecast_provider.artifacts import ForecastArtifactRepository, LocalArtifactStore
from forecast_provider.artifacts.contracts import ArtifactError
from forecast_provider.contracts import ForecastDataset, ProviderConfig, RunContext
from forecast_provider.errors import ContractViolationError, NonRetryableProviderError
from forecast_provider.evaluation import compare_runs
from forecast_provider.frames import validate_predict_frame
from forecast_provider.providers.causal_series import prepare_daily_series
from forecast_provider.providers.statsforecast_codec import StatsForecastETSCodec
from forecast_provider.registry import registry
from forecast_provider.run_context import cutoff_for_origin
from forecast_provider.runner import run_fixed_provider

TRAIN_END = date(2024, 4, 30)


def make_dataset() -> ForecastDataset:
    return ForecastDataset(
        dataset_snapshot_id="dss-statsforecast",
        selection_version="sel-statsforecast",
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
        "statsforecast-ets",
        "auto_ets_weekly",
        {"season_length": 7, "model": "ZZZ"},
        (),
        preprocessing_version="statsforecast-causal-ffill-v1",
    )


def make_context(tmp_path, origin: date = TRAIN_END) -> RunContext:
    return RunContext(
        "run-statsforecast",
        "exp-statsforecast",
        7,
        datetime.now(UTC) + timedelta(hours=1),
        tmp_path,
        tmp_path,
        "cpu-small",
        logging.getLogger("statsforecast-test"),
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
    provider = registry.create("statsforecast-ets")
    dataset, config = make_dataset(), make_config()
    context = make_context(tmp_path)
    data = make_data()
    train = data[data.ds.le(pd.Timestamp(TRAIN_END))]
    model = provider.fit_parameters(train, dataset, config, context)
    return provider, dataset, config, context, data, model


def test_metadata_registry_and_explicit_configuration(tmp_path) -> None:
    provider = registry.create("statsforecast-ets")
    metadata = provider.metadata()
    assert metadata.library_name == "statsforecast"
    assert metadata.library_version == "2.1.1"
    assert metadata.capabilities.license == "Apache-2.0"
    assert metadata.capabilities.eligible_for_primary_ranking
    assert not metadata.capabilities.supports_intervals
    assert provider.validate(make_dataset(), make_config()).ok

    bad_interval = ProviderConfig(
        "statsforecast-ets",
        "auto_ets_weekly",
        {"season_length": 7, "model": "ZZZ"},
        (0.8,),
        preprocessing_version="statsforecast-causal-ffill-v1",
    )
    assert not provider.validate(make_dataset(), bad_interval).ok
    with pytest.raises(ContractViolationError):
        provider.fit_parameters(make_data(), make_dataset(), bad_interval, make_context(tmp_path))


def test_baseline_registry_imports_without_optional_providers() -> None:
    code = """
import importlib.util
original = importlib.util.find_spec
def without_optional(name, *args, **kwargs):
    hidden = {'statsforecast', 'mlforecast', 'timesfm'}
    return None if name in hidden else original(name, *args, **kwargs)
importlib.util.find_spec = without_optional
from forecast_provider.registry import registry
assert [item.provider_id for item in registry.list_metadata()] == ['builtin-baseline']
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_causal_forward_fill_preserves_zero_and_drops_leading_missing() -> None:
    frame = pd.DataFrame(
        {
            "unique_id": "A",
            "ds": pd.date_range("2024-01-01", periods=5),
            "y": [np.nan, 0.0, np.nan, 4.0, 99.0],
        }
    )
    series, actual, imputed = prepare_daily_series(
        frame, date(2024, 1, 1), date(2024, 1, 4)
    )
    assert series.tolist() == [0.0, 0.0, 4.0]
    assert series.index[0] == pd.Timestamp("2024-01-02")
    assert actual == 2 and imputed == 1
    assert 99.0 not in series.to_numpy()


@pytest.mark.parametrize("level", [0.0, 5.0])
def test_constant_series_roundtrips_as_nonseasonal_autoets(tmp_path, level) -> None:
    provider, dataset, config, context, data, _ = fitted(tmp_path)
    data["y"] = level
    train = data[data.ds.le(pd.Timestamp(TRAIN_END))]
    model = provider.fit_parameters(train, dataset, config, context)
    repository = ForecastArtifactRepository(
        LocalArtifactStore(tmp_path / f"objects-{level}"), [StatsForecastETSCodec()]
    )
    artifact = repository.save_model(model, dataset, config, context)
    restored = repository.load_model(artifact, dataset, config, context)
    ref = provider.refresh_context(restored, train, TRAIN_END, context)
    predicted = provider.predict(
        restored, ref, make_future(TRAIN_END), list(range(1, 16)), context
    )
    assert len(predicted) == 30
    assert np.allclose(predicted.yhat, level)


def test_library_fit_failure_is_not_reported_as_short_history(tmp_path, monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("library failure")

    monkeypatch.setattr(
        "forecast_provider.providers.statsforecast_ets.fit_auto_ets", fail
    )
    provider = registry.create("statsforecast-ets")
    train = make_data()
    train = train[train.ds.le(pd.Timestamp(TRAIN_END))]
    with pytest.raises(NonRetryableProviderError, match="学習が全対象で失敗"):
        provider.fit_parameters(
            train, make_dataset(), make_config(), make_context(tmp_path)
        )


def test_fixed_parameters_refresh_history_and_batch_predict(tmp_path) -> None:
    provider, dataset, _, context, data, model = fitted(tmp_path)
    signatures = copy.deepcopy(model.state["parameter_signatures"])
    first_context = provider.refresh_context(
        model, data[data.ds.le(pd.Timestamp(TRAIN_END))], TRAIN_END, context
    )
    first = provider.predict(
        model, first_context, make_future(TRAIN_END), list(range(1, 16)), context
    )
    validate_predict_frame(first, expected_targets=make_future(TRAIN_END))
    assert len(first) == 30 and set(first.forecast_kind) == {"POINT"}

    later = date(2024, 5, 7)
    later_context = context.for_origin(later)
    refreshed = provider.refresh_context(
        model, data[data.ds.le(pd.Timestamp(later))], later, later_context
    )
    second = provider.predict(
        model, refreshed, make_future(later, range(1, 9)), list(range(1, 9)), later_context
    )
    assert model.state["parameter_signatures"] == signatures
    assert refreshed.state["parameter_signatures"] == signatures
    assert not np.allclose(
        first[first.unique_id.eq("A")].yhat_raw.iloc[:8],
        second[second.unique_id.eq("A")].yhat_raw,
    )
    assert dataset.max_horizon == 15


def test_origin_forecast_does_not_read_future_actuals(tmp_path) -> None:
    provider, _, _, context, data, model = fitted(tmp_path)
    altered = data.copy()
    altered.loc[altered.ds.gt(pd.Timestamp(TRAIN_END)), "y"] = 999999.0
    outputs = []
    for source in (data, altered):
        history = source[source.ds.le(pd.Timestamp(TRAIN_END))]
        ref = provider.refresh_context(model, history, TRAIN_END, context)
        outputs.append(
            provider.predict(model, ref, make_future(TRAIN_END), list(range(1, 16)), context)
        )
    pd.testing.assert_frame_equal(outputs[0], outputs[1])
    with pytest.raises(ContractViolationError):
        provider.predict(
            model,
            provider.refresh_context(model, history, TRAIN_END, context),
            make_future(TRAIN_END).assign(y=1.0),
            list(range(1, 16)),
            context,
        )


def test_json_artifact_roundtrip_and_signature_tamper_detection(tmp_path) -> None:
    provider, dataset, config, context, data, model = fitted(tmp_path)
    codec = StatsForecastETSCodec()
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
    payload["parameter_signatures"]["A"] = "0" * 64
    with pytest.raises(ArtifactError):
        codec.decode_model(payload, model, dataset, config, context)


def test_common_fixed_runner_executes_statsforecast(tmp_path) -> None:
    result = run_fixed_provider(
        make_data(),
        make_dataset(),
        make_config(),
        make_context(tmp_path),
        availability_mode="ASSUMED",
    )
    assert result["status"] == "SUCCESS"
    assert result["fit_calls"] == 1
    assert result["errors"] == []
    assert len(result["predictions"]) == 30


def test_baseline_and_statsforecast_share_official_comparison(tmp_path) -> None:
    data, dataset, context = make_data(), make_dataset(), make_context(tmp_path)
    stats = run_fixed_provider(
        data, dataset, make_config(), context, availability_mode="ASSUMED"
    )["predictions"]
    baseline_config = ProviderConfig(
        "builtin-baseline",
        "moving_average_28",
        {},
        (),
        preprocessing_version="daily-nan-preserving-v1",
    )
    baseline = run_fixed_provider(
        data, dataset, baseline_config, context, availability_mode="ASSUMED"
    )["predictions"]
    comparison = compare_runs(
        {"baseline": dataset, "autoets": dataset},
        {"baseline": baseline, "autoets": stats},
        data,
        truth_version="synthetic-v1",
        mode="primary",
    )
    assert comparison["official_ranking_ready"]
    assert comparison["official_runs"] == ["baseline", "autoets"]
    assert all(score["run_success_rate"] == 1 for score in comparison["scores"].values())
