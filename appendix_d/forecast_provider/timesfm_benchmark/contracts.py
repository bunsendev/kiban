"""TimesFM運用ベンチマークの入力契約。"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from ..providers.timesfm_runtime import MODEL_PARAMS

REPORT_FORMAT_VERSION = 1
DEFAULT_PROFILE_NAME = "cpu-timesfm"
DEFAULT_CPU_LIMIT = 2.0
DEFAULT_MEMORY_LIMIT_BYTES = 4 * 1024**3
DEFAULT_STEP_LIMIT_SECONDS = 600.0


def _bounded_integer(name: str, value: Any, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name}は{minimum}以上{maximum}以下の整数です")
    return value


def _positive_number(name: str, value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError(f"{name}は正の数です")
    return float(value)


@dataclass(frozen=True)
class BenchmarkWorkload:
    """人工系列で固定する計測負荷。"""

    series_count: int = 3
    context_length: int = MODEL_PARAMS["max_context"]
    horizon: int = 15
    warmup_runs: int = 1
    measured_runs: int = 3

    def __post_init__(self) -> None:
        _bounded_integer("series_count", self.series_count, 1, 50)
        _bounded_integer("context_length", self.context_length, 64, MODEL_PARAMS["max_context"])
        _bounded_integer("horizon", self.horizon, 1, MODEL_PARAMS["max_horizon"])
        _bounded_integer("warmup_runs", self.warmup_runs, 1, 5)
        _bounded_integer("measured_runs", self.measured_runs, 1, 20)

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkLimits:
    """Composeのresource profileと対応する技術判定上限。"""

    profile_name: str = DEFAULT_PROFILE_NAME
    cpu_limit: float = DEFAULT_CPU_LIMIT
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES
    max_model_initialize_seconds: float = DEFAULT_STEP_LIMIT_SECONDS
    max_forecast_seconds: float = DEFAULT_STEP_LIMIT_SECONDS
    max_peak_rss_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES

    def __post_init__(self) -> None:
        if not isinstance(self.profile_name, str) or not self.profile_name.strip():
            raise ValueError("profile_nameが必要です")
        _positive_number("cpu_limit", self.cpu_limit)
        _bounded_integer("memory_limit_bytes", self.memory_limit_bytes, 256 * 1024**2, 64 * 1024**3)
        _positive_number("max_model_initialize_seconds", self.max_model_initialize_seconds)
        _positive_number("max_forecast_seconds", self.max_forecast_seconds)
        _bounded_integer("max_peak_rss_bytes", self.max_peak_rss_bytes, 1, 64 * 1024**3)
        if self.max_peak_rss_bytes > self.memory_limit_bytes:
            raise ValueError("max_peak_rss_bytesはmemory_limit_bytes以下にします")

    def as_dict(self) -> dict[str, str | float | int]:
        return asdict(self)
