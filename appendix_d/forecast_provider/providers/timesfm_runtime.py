"""TimesFM 2.5 PyTorch runtimeの遅延ロードとバッチ予測。"""

from __future__ import annotations

import math
import threading
from typing import Any

import numpy as np

from ..errors import NonRetryableProviderError
from .timesfm_checkpoint import CheckpointRef

MODEL_PARAMS = {
    "max_context": 512,
    "max_horizon": 400,
    "normalize_inputs": True,
    "force_flip_invariance": True,
}

_RUNTIMES: dict[tuple[str, str], Any] = {}
_LOCK = threading.Lock()


def forecast_timesfm(
    checkpoint: CheckpointRef, inputs: list[np.ndarray], horizon: int
) -> np.ndarray:
    """固定設定のローカルruntimeでPOINT予測だけを返す。"""
    if not inputs or horizon <= 0 or horizon > MODEL_PARAMS["max_horizon"]:
        raise ValueError("TimesFMの入力またはhorizonが不正です")
    arrays = [np.asarray(value, dtype="float32").copy() for value in inputs]
    if any(
        value.ndim != 1
        or value.size == 0
        or value.size > MODEL_PARAMS["max_context"]
        or not np.isfinite(value).all()
        for value in arrays
    ):
        raise ValueError("TimesFMのcontextは有限な一次元系列です")
    runtime = _runtime(checkpoint)
    points, _ = runtime.forecast(horizon=horizon, inputs=arrays)
    result = np.asarray(points, dtype="float64")
    if result.shape != (len(arrays), horizon) or not np.isfinite(result).all():
        raise ValueError("TimesFMが有限なバッチPOINT予測を返しませんでした")
    return result


def _runtime(checkpoint: CheckpointRef):
    return load_timesfm_runtime(checkpoint)


def load_timesfm_runtime(checkpoint: CheckpointRef):
    """検証済みcheckpointから固定設定runtimeをロードしてprocess内で再利用する。"""
    key = (str(checkpoint.path), checkpoint.sha256)
    with _LOCK:
        cached = _RUNTIMES.get(key)
        if cached is not None:
            return cached
        try:
            import torch
            from timesfm import ForecastConfig, TimesFM_2p5_200M_torch
        except (ImportError, AttributeError) as exc:
            raise NonRetryableProviderError(
                "TimesFM Workerにはtimesfm[torch]依存が必要です"
            ) from exc
        torch.set_num_threads(1)
        # Hub mixinを経由せず、検証済みのローカルfileを直接ロードする。
        # これにより推論経路からnetwork lookup自体を除外する。
        model = TimesFM_2p5_200M_torch(torch_compile=False)
        model.load_checkpoint(str(checkpoint.path), torch_compile=False)
        model.compile(
            ForecastConfig(
                max_context=MODEL_PARAMS["max_context"],
                max_horizon=MODEL_PARAMS["max_horizon"],
                per_core_batch_size=1,
                normalize_inputs=MODEL_PARAMS["normalize_inputs"],
                force_flip_invariance=MODEL_PARAMS["force_flip_invariance"],
                infer_is_positive=False,
                use_continuous_quantile_head=False,
                fix_quantile_crossing=False,
            )
        )
        _RUNTIMES[key] = model
        return model


def clear_runtime_cache() -> None:
    """テストと明示的なWorker再初期化用。"""
    with _LOCK:
        _RUNTIMES.clear()


def runtime_signature() -> str:
    """実験定義に固定する推論設定を安定した文字列で返す。"""
    values = (
        MODEL_PARAMS["max_context"],
        MODEL_PARAMS["max_horizon"],
        int(MODEL_PARAMS["normalize_inputs"]),
        int(MODEL_PARAMS["force_flip_invariance"]),
    )
    return ":".join(str(value) for value in values)


def validate_runtime_params(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != set(MODEL_PARAMS):
        return False
    if any(isinstance(value[name], bool) for name in ("max_context", "max_horizon")):
        return False
    return value == MODEL_PARAMS and all(
        math.isfinite(float(value[name])) for name in ("max_context", "max_horizon")
    )
