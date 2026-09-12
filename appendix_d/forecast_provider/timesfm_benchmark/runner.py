"""人工系列でTimesFM専用Workerを初期化・warm-up・反復計測する。"""

from __future__ import annotations

import math
import os
import statistics
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..errors import NonRetryableProviderError
from ..providers.timesfm_checkpoint import (
    CHECKPOINT_SHA256,
    CHECKPOINT_SIZE,
    CheckpointRef,
    resolve_checkpoint,
)
from ..providers.timesfm_runtime import (
    MODEL_PARAMS,
    clear_runtime_cache,
    forecast_timesfm,
    load_timesfm_runtime,
    runtime_signature,
)
from .contracts import (
    REPORT_FORMAT_VERSION,
    BenchmarkLimits,
    BenchmarkWorkload,
)
from .environment import runtime_environment
from .measurement import Measurement, ProcessProbe, SystemProcessProbe, measure_call
from .report import condition_fingerprint, publish_report

CheckpointResolver = Callable[[str | Path | None], CheckpointRef]
RuntimeLoader = Callable[[CheckpointRef], Any]
Forecaster = Callable[[CheckpointRef, list[np.ndarray], int], np.ndarray]


def _artificial_inputs(workload: BenchmarkWorkload) -> list[np.ndarray]:
    index = np.arange(workload.context_length, dtype="float32")
    return [
        np.asarray(
            20.0
            + series_index * 3.0
            + index * 0.02
            + np.sin((index + series_index) * (2.0 * math.pi / 7.0)) * 2.0,
            dtype="float32",
        )
        for series_index in range(workload.series_count)
    ]


def _nearest_rank(values: list[float], proportion: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * proportion) - 1)]


def _measurement_summary(samples: list[Measurement]) -> dict[str, float]:
    walls = [sample.wall_seconds for sample in samples]
    cpus = [sample.cpu_seconds for sample in samples]
    return {
        "wall_min_seconds": min(walls),
        "wall_median_seconds": statistics.median(walls),
        "wall_p95_seconds": _nearest_rank(walls, 0.95),
        "wall_max_seconds": max(walls),
        "cpu_median_seconds": statistics.median(cpus),
        "cpu_max_seconds": max(cpus),
    }


def _check(check_id: str, passed: bool, actual: Any, expected: Any) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "PASSED" if passed else "FAILED",
        "actual": actual,
        "expected": expected,
    }


def _assessment(
    *,
    checkpoint: CheckpointRef,
    checkpoint_read_only: bool,
    initialization: Measurement,
    samples: list[Measurement],
    peak_rss_bytes: int,
    finite_outputs: bool,
    environment: dict[str, Any],
    limits: BenchmarkLimits,
) -> dict[str, Any]:
    forecast_max = max(sample.wall_seconds for sample in samples)
    actual_cpu_limit = environment.get("cgroup_cpu_limit")
    actual_memory_limit = environment.get("cgroup_memory_limit_bytes")
    checks = [
        _check(
            "CHECKPOINT_SHA256",
            checkpoint.sha256 == CHECKPOINT_SHA256 and checkpoint.size_bytes == CHECKPOINT_SIZE,
            {"sha256": checkpoint.sha256, "size_bytes": checkpoint.size_bytes},
            {"sha256": CHECKPOINT_SHA256, "size_bytes": CHECKPOINT_SIZE},
        ),
        _check("CHECKPOINT_READ_ONLY", checkpoint_read_only, checkpoint_read_only, True),
        _check(
            "MODEL_INITIALIZE_SECONDS",
            initialization.wall_seconds <= limits.max_model_initialize_seconds,
            initialization.wall_seconds,
            {"maximum": limits.max_model_initialize_seconds},
        ),
        _check(
            "FORECAST_SECONDS",
            forecast_max <= limits.max_forecast_seconds,
            forecast_max,
            {"maximum_per_run": limits.max_forecast_seconds},
        ),
        _check(
            "PEAK_RSS_BYTES",
            peak_rss_bytes <= limits.max_peak_rss_bytes,
            peak_rss_bytes,
            {"maximum": limits.max_peak_rss_bytes},
        ),
        _check("FINITE_OUTPUTS", finite_outputs, finite_outputs, True),
        _check(
            "CGROUP_CPU_LIMIT",
            actual_cpu_limit is not None and actual_cpu_limit <= limits.cpu_limit * 1.01,
            actual_cpu_limit,
            {"maximum": limits.cpu_limit},
        ),
        _check(
            "CGROUP_MEMORY_LIMIT",
            actual_memory_limit is not None and actual_memory_limit <= limits.memory_limit_bytes,
            actual_memory_limit,
            {"maximum": limits.memory_limit_bytes},
        ),
    ]
    return {
        "outcome": "PASSED" if all(item["status"] == "PASSED" for item in checks) else "FAILED",
        "checks": checks,
        "limitations": [
            "人工系列による専用Workerの技術計測であり、実データ精度を評価していない。",
            "測定値は実行host、Docker、CPU負荷に依存し、本番SLAを保証しない。",
            "peak RSSは専用processの起動後からの累積最大値である。",
        ],
    }


def collect_benchmark(
    workload: BenchmarkWorkload,
    limits: BenchmarkLimits,
    checkpoint_path: str | Path | None = None,
    *,
    checkpoint_resolver: CheckpointResolver = resolve_checkpoint,
    runtime_loader: RuntimeLoader = load_timesfm_runtime,
    forecaster: Forecaster = forecast_timesfm,
    probe: ProcessProbe | None = None,
    environment_reader: Callable[[], dict[str, Any]] = runtime_environment,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    cache_clearer: Callable[[], None] = clear_runtime_cache,
    checkpoint_read_only_reader: Callable[[Path], bool] = lambda path: not os.access(
        path, os.W_OK
    ),
) -> dict[str, Any]:
    """重みを保存せず、初期化と反復推論の技術測定値を返す。"""
    process_probe = probe or SystemProcessProbe()

    def execute() -> dict[str, Any]:
        checkpoint, verification = measure_call(
            lambda: checkpoint_resolver(checkpoint_path), process_probe
        )
        checkpoint_read_only = checkpoint_read_only_reader(checkpoint.path)
        if not checkpoint_read_only:
            raise NonRetryableProviderError(
                "TimesFM checkpointは専用Workerからread-onlyである必要があります"
            )
        cache_clearer()
        _, initialization = measure_call(lambda: runtime_loader(checkpoint), process_probe)
        inputs = _artificial_inputs(workload)
        warmups: list[Measurement] = []
        samples: list[Measurement] = []
        finite_outputs = True
        for _ in range(workload.warmup_runs):
            output, measurement = measure_call(
                lambda: forecaster(checkpoint, inputs, workload.horizon), process_probe
            )
            finite_outputs = finite_outputs and _valid_output(output, workload)
            warmups.append(measurement)
        for _ in range(workload.measured_runs):
            output, measurement = measure_call(
                lambda: forecaster(checkpoint, inputs, workload.horizon), process_probe
            )
            finite_outputs = finite_outputs and _valid_output(output, workload)
            samples.append(measurement)
        return {
            "checkpoint": checkpoint,
            "checkpoint_read_only": checkpoint_read_only,
            "verification": verification,
            "initialization": initialization,
            "warmups": warmups,
            "samples": samples,
            "finite_outputs": finite_outputs,
        }

    measured, total = measure_call(execute, process_probe)
    checkpoint = measured["checkpoint"]
    checkpoint_read_only = measured["checkpoint_read_only"]
    environment = environment_reader()
    conditions = {
        "provider_id": "timesfm-2p5",
        "model_name": "timesfm_2p5_200m_zero_shot",
        "runtime_signature": runtime_signature(),
        "runtime_params": MODEL_PARAMS,
        "checkpoint": {
            "weights_id": checkpoint.weights_id,
            "sha256": checkpoint.sha256,
            "size_bytes": checkpoint.size_bytes,
            "effectively_read_only": checkpoint_read_only,
        },
        "workload": workload.as_dict(),
        "resource_profile": limits.as_dict(),
        "environment": environment,
    }
    assessment = _assessment(
        checkpoint=checkpoint,
        checkpoint_read_only=checkpoint_read_only,
        initialization=measured["initialization"],
        samples=measured["samples"],
        peak_rss_bytes=total.peak_rss_bytes,
        finite_outputs=measured["finite_outputs"],
        environment=environment,
        limits=limits,
    )
    measured_at = now().astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "format_version": REPORT_FORMAT_VERSION,
        "benchmark_id": condition_fingerprint(conditions),
        "measured_at": measured_at,
        "conditions": conditions,
        "measurements": {
            "checkpoint_verification": measured["verification"].as_dict(),
            "model_initialization": measured["initialization"].as_dict(),
            "warmup_runs": [item.as_dict() for item in measured["warmups"]],
            "forecast_runs": [item.as_dict() for item in measured["samples"]],
            "forecast_summary": _measurement_summary(measured["samples"]),
            "total": total.as_dict(),
        },
        "assessment": assessment,
    }


def _valid_output(output: np.ndarray, workload: BenchmarkWorkload) -> bool:
    array = np.asarray(output)
    return array.shape == (workload.series_count, workload.horizon) and bool(
        np.isfinite(array).all()
    )


def run_benchmark(
    workload: BenchmarkWorkload,
    limits: BenchmarkLimits,
    output_root: Path,
    checkpoint_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = collect_benchmark(workload, limits, checkpoint_path)
    report_uri, report_sha256 = publish_report(payload, output_root)
    return {
        "benchmark_id": payload["benchmark_id"],
        "outcome": payload["assessment"]["outcome"],
        "report_uri": report_uri,
        "report_sha256": report_sha256,
    }
