"""TimesFM 2.5 Providerの固定重み、未来非参照、保存契約。"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import logging
import os
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("timesfm")

from forecast_provider.artifacts import ForecastArtifactRepository, LocalArtifactStore
from forecast_provider.artifacts.contracts import ArtifactError
from forecast_provider.contracts import ForecastDataset, ProviderConfig, RunContext
from forecast_provider.errors import ContractViolationError, NonRetryableProviderError
from forecast_provider.frames import validate_predict_frame
from forecast_provider.providers import timesfm_checkpoint as checkpoint_module
from forecast_provider.providers.timesfm_checkpoint import (
    CHECKPOINT_SHA256,
    CHECKPOINT_SIZE,
    CheckpointRef,
)
from forecast_provider.providers.timesfm_codec import TimesFM2p5Codec
from forecast_provider.providers.timesfm_runtime import MODEL_PARAMS, forecast_timesfm
from forecast_provider.registry import registry
from forecast_provider.run_context import cutoff_for_origin
from forecast_provider.runner import run_fixed_provider

TRAIN_END = date(2024, 4, 30)


def make_dataset() -> ForecastDataset:
    return ForecastDataset(
        dataset_snapshot_id="dss-timesfm",
        selection_version="sel-timesfm",
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
        "timesfm-2p5",
        "timesfm_2p5_200m_zero_shot",
        dict(MODEL_PARAMS),
        (),
        preprocessing_version="timesfm-causal-ffill-context512-v1",
    )


def make_context(tmp_path, origin: date = TRAIN_END) -> RunContext:
    return RunContext(
        "run-timesfm",
        "exp-timesfm",
        7,
        datetime.now(UTC) + timedelta(hours=1),
        tmp_path,
        tmp_path,
        "cpu-timesfm",
        logging.getLogger("timesfm-test"),
        availability_mode="ASSUMED",
        cutoff_at=cutoff_for_origin(origin),
        origin_date=origin,
    )


def make_data(end: str = "2024-05-15") -> pd.DataFrame:
    days = pd.date_range("2024-01-01", end)
    frames = []
    for offset, uid in enumerate(("A", "B")):
        y = 20.0 + offset * 3 + (days.dayofweek == 0) * 4 + np.arange(len(days)) * 0.1
        frames.append(pd.DataFrame({"unique_id": uid, "ds": days, "y": y}))
    return pd.concat(frames, ignore_index=True)


def make_future(origin: date, horizons=range(1, 16)) -> pd.DataFrame:
    timestamp = pd.Timestamp(origin)
    return pd.DataFrame(
        [
            {
                "unique_id": uid,
                "origin_date": timestamp,
                "target_date": timestamp + pd.Timedelta(days=horizon),
                "horizon": horizon,
            }
            for uid in ("A", "B")
            for horizon in horizons
        ]
    )


@pytest.fixture
def fake_runtime(monkeypatch, tmp_path):
    ref = CheckpointRef(tmp_path / "model.safetensors", CHECKPOINT_SHA256, CHECKPOINT_SIZE)

    def predict(_checkpoint, inputs, horizon):
        return np.asarray(
            [[float(values[-1]) + step for step in range(1, horizon + 1)] for values in inputs]
        )

    monkeypatch.setattr("forecast_provider.providers.timesfm_2p5.resolve_checkpoint", lambda: ref)
    monkeypatch.setattr("forecast_provider.providers.timesfm_2p5.forecast_timesfm", predict)
    return ref


def fitted(tmp_path, fake_runtime):
    provider = registry.create("timesfm-2p5")
    dataset, config = make_dataset(), make_config()
    context, data = make_context(tmp_path), make_data()
    train = data[data.ds.le(pd.Timestamp(TRAIN_END))]
    model = provider.fit_parameters(train, dataset, config, context)
    return provider, dataset, config, context, data, model


def test_metadata_registry_and_fixed_configuration() -> None:
    provider = registry.create("timesfm-2p5")
    metadata = provider.metadata()
    assert metadata.library_version == "3.0.2"
    assert metadata.category == "時系列基盤モデル"
    assert metadata.capabilities.license == "Apache-2.0"
    assert metadata.capabilities.offline_capable
    assert provider.validate(make_dataset(), make_config()).ok

    bad = ProviderConfig(
        "timesfm-2p5",
        "timesfm_2p5_200m_zero_shot",
        {**MODEL_PARAMS, "max_context": 256},
        (),
        preprocessing_version="timesfm-causal-ffill-context512-v1",
    )
    assert not provider.validate(make_dataset(), bad).ok


def test_checkpoint_requires_exact_local_file(tmp_path, monkeypatch) -> None:
    content = b"fixed tiny checkpoint"
    path = tmp_path / "model.safetensors"
    path.write_bytes(content)
    monkeypatch.setattr(checkpoint_module, "CHECKPOINT_SIZE", len(content))
    monkeypatch.setattr(checkpoint_module, "CHECKPOINT_SHA256", hashlib.sha256(content).hexdigest())
    checkpoint_module._cached_sha256.cache_clear()
    assert checkpoint_module.resolve_checkpoint(path).path == path.resolve()

    path.write_bytes(b"x" * len(content))
    checkpoint_module._cached_sha256.cache_clear()
    with pytest.raises(NonRetryableProviderError, match="SHA-256"):
        checkpoint_module.resolve_checkpoint(path)

    path.write_bytes(content + b"tampered")
    checkpoint_module._cached_sha256.cache_clear()
    with pytest.raises(NonRetryableProviderError, match="size"):
        checkpoint_module.resolve_checkpoint(path)


def test_runtime_validates_batch_shape(monkeypatch, tmp_path) -> None:
    class Runtime:
        def forecast(self, *, horizon, inputs):
            return np.tile(np.arange(horizon), (len(inputs), 1)), None

    monkeypatch.setattr(
        "forecast_provider.providers.timesfm_runtime._runtime", lambda checkpoint: Runtime()
    )
    ref = CheckpointRef(tmp_path / "model.safetensors", CHECKPOINT_SHA256, CHECKPOINT_SIZE)
    result = forecast_timesfm(ref, [np.arange(64)], 3)
    assert result.shape == (1, 3)
    with pytest.raises(ValueError):
        forecast_timesfm(ref, [np.arange(513)], 3)


def test_zero_shot_refresh_prediction_and_future_values_are_not_read(
    tmp_path, fake_runtime
) -> None:
    provider, _, _, context, data, model = fitted(tmp_path, fake_runtime)
    original_state = copy.deepcopy(model.state)
    history = data[data.ds.le(pd.Timestamp(TRAIN_END))]
    ref = provider.refresh_context(model, history, TRAIN_END, context)
    expected = provider.predict(model, ref, make_future(TRAIN_END), list(range(1, 16)), context)
    validate_predict_frame(expected, expected_targets=make_future(TRAIN_END))
    assert len(expected) == 30
    assert set(expected.forecast_kind) == {"POINT"}
    assert all(len(series) <= 512 for series in ref.state["series"].values())

    changed = data.copy()
    changed.loc[changed.ds.gt(pd.Timestamp(TRAIN_END)), "y"] = 999999.0
    changed_ref = provider.refresh_context(
        model, changed[changed.ds.le(pd.Timestamp(TRAIN_END))], TRAIN_END, context
    )
    actual = provider.predict(
        model, changed_ref, make_future(TRAIN_END), list(range(1, 16)), context
    )
    pd.testing.assert_frame_equal(expected, actual)
    assert model.state == original_state
    with pytest.raises(ContractViolationError):
        provider.predict(
            model,
            ref,
            make_future(TRAIN_END).assign(y=1.0),
            list(range(1, 16)),
            context,
        )


def test_artifact_roundtrip_excludes_weights_and_detects_tamper(
    tmp_path, fake_runtime
) -> None:
    provider, dataset, config, context, data, model = fitted(tmp_path, fake_runtime)
    codec = TimesFM2p5Codec()
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
    targets = make_future(TRAIN_END, [1, 7, 15])
    expected = provider.predict(model, ref, targets, [1, 7, 15], context)
    actual = provider.predict(
        restored_model, restored_ref, targets, [1, 7, 15], context
    )
    pd.testing.assert_frame_equal(expected, actual)
    artifact = (tmp_path / "objects" / f"{model_artifact.sha256}.json").read_bytes()
    assert str(tmp_path).encode() not in artifact and len(artifact) < 10_000

    payload = codec.encode_model(model, dataset, config, context)
    payload["checkpoint_sha256"] = "0" * 64
    with pytest.raises(ArtifactError, match="checkpoint"):
        codec.decode_model(payload, model, dataset, config, context)


def test_common_runner_uses_timesfm_provider(tmp_path, fake_runtime) -> None:
    result = run_fixed_provider(
        make_data(),
        make_dataset(),
        make_config(),
        make_context(tmp_path),
        availability_mode="ASSUMED",
    )
    assert len(result["predictions"]) == 30
    assert result["status"] == "SUCCESS"


@pytest.mark.skipif(
    not os.environ.get("KIBAN_TEST_TIMESFM_CHECKPOINT")
    or importlib.util.find_spec("torch") is None,
    reason="実checkpointとPyTorchを指定した任意smoke test",
)
def test_real_checkpoint_smoke() -> None:
    ref = checkpoint_module.resolve_checkpoint(os.environ["KIBAN_TEST_TIMESFM_CHECKPOINT"])
    output = forecast_timesfm(ref, [np.arange(64, dtype="float32")], 1)
    assert output.shape == (1, 1) and np.isfinite(output).all()
