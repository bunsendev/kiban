"""TimesFM専用Workerの計測、判定、内容アドレス保存。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from forecast_provider.errors import NonRetryableProviderError
from forecast_provider.providers.timesfm_checkpoint import (
    CHECKPOINT_SHA256,
    CHECKPOINT_SIZE,
    CheckpointRef,
)
from forecast_provider.timesfm_benchmark import BenchmarkLimits, BenchmarkWorkload
from forecast_provider.timesfm_benchmark import cli as benchmark_cli
from forecast_provider.timesfm_benchmark.measurement import SystemProcessProbe
from forecast_provider.timesfm_benchmark.report import publish_report
from forecast_provider.timesfm_benchmark.runner import collect_benchmark


class FakeProbe:
    def __init__(self) -> None:
        self.wall = 0
        self.cpu = 0
        self.rss = 900_000_000

    def wall_ns(self) -> int:
        self.wall += 1_000_000_000
        return self.wall

    def cpu_ns(self) -> int:
        self.cpu += 500_000_000
        return self.cpu

    def peak_rss_bytes(self) -> int:
        self.rss += 10_000_000
        return self.rss


def fake_environment() -> dict:
    return {
        "python_version": "3.12.0",
        "platform": "Linux-test",
        "machine": "x86_64",
        "timesfm_version": "3.0.2",
        "torch_version": "2.14.0+cpu",
        "logical_cpu_count": 8,
        "cgroup_cpu_limit": 2.0,
        "cgroup_memory_limit_bytes": 4 * 1024**3,
    }


def collect(
    tmp_path: Path,
    limits: BenchmarkLimits | None = None,
    measured_at: datetime = datetime(2026, 9, 12, tzinfo=UTC),
) -> dict:
    ref = CheckpointRef(tmp_path / "model.safetensors", CHECKPOINT_SHA256, CHECKPOINT_SIZE)
    loaded: list[CheckpointRef] = []

    def loader(checkpoint: CheckpointRef) -> object:
        loaded.append(checkpoint)
        return object()

    def forecast(checkpoint: CheckpointRef, inputs: list[np.ndarray], horizon: int) -> np.ndarray:
        assert checkpoint == ref
        assert all(value.shape == (64,) for value in inputs)
        return np.ones((len(inputs), horizon), dtype="float64")

    report = collect_benchmark(
        BenchmarkWorkload(
            series_count=2, context_length=64, horizon=7, warmup_runs=1, measured_runs=3
        ),
        limits or BenchmarkLimits(),
        checkpoint_resolver=lambda _: ref,
        runtime_loader=loader,
        forecaster=forecast,
        probe=FakeProbe(),
        environment_reader=fake_environment,
        now=lambda: measured_at,
        cache_clearer=lambda: None,
    )
    assert loaded == [ref]
    return report


def test_contracts_reject_excessive_or_non_finite_values() -> None:
    with pytest.raises(ValueError, match="context_length"):
        BenchmarkWorkload(context_length=513)
    with pytest.raises(ValueError, match="series_count"):
        BenchmarkWorkload(series_count=True)
    with pytest.raises(ValueError, match="cpu_limit"):
        BenchmarkLimits(cpu_limit=float("inf"))
    with pytest.raises(ValueError, match="max_peak_rss_bytes"):
        BenchmarkLimits(max_peak_rss_bytes=5 * 1024**3)


def test_collect_separates_initialization_warmup_and_measured_runs(tmp_path: Path) -> None:
    report = collect(tmp_path)
    assert report["format_version"] == 1
    assert report["assessment"]["outcome"] == "PASSED"
    assert report["conditions"]["workload"] == {
        "series_count": 2,
        "context_length": 64,
        "horizon": 7,
        "warmup_runs": 1,
        "measured_runs": 3,
    }
    measurements = report["measurements"]
    assert measurements["model_initialization"]["wall_seconds"] == 1.0
    assert len(measurements["warmup_runs"]) == 1
    assert len(measurements["forecast_runs"]) == 3
    assert measurements["forecast_summary"]["wall_p95_seconds"] == 1.0
    serialized = json.dumps(report, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "path" not in report["conditions"]["checkpoint"]
    assert "predictions" not in serialized


def test_benchmark_id_excludes_measurement_time_and_limits_can_fail(tmp_path: Path) -> None:
    first = collect(tmp_path)
    later = collect(tmp_path, measured_at=datetime(2026, 9, 13, tzinfo=UTC))
    failed = collect(tmp_path, BenchmarkLimits(max_model_initialize_seconds=0.5))
    assert first["benchmark_id"] == later["benchmark_id"]
    assert first["measured_at"] != later["measured_at"]
    assert failed["assessment"]["outcome"] == "FAILED"
    checks = {item["check_id"]: item for item in failed["assessment"]["checks"]}
    assert checks["MODEL_INITIALIZE_SECONDS"]["status"] == "FAILED"
    # 判定条件が変われば、同じcheckpointと人工系列でも別benchmark IDになる。
    assert first["benchmark_id"] != failed["benchmark_id"]


def test_checkpoint_failure_stops_before_runtime_load(tmp_path: Path) -> None:
    loaded = False

    def reject(_: str | Path | None) -> CheckpointRef:
        raise NonRetryableProviderError("checkpoint rejected")

    def loader(_: CheckpointRef) -> object:
        nonlocal loaded
        loaded = True
        return object()

    with pytest.raises(NonRetryableProviderError, match="checkpoint rejected"):
        collect_benchmark(
            BenchmarkWorkload(series_count=1, context_length=64, horizon=1),
            BenchmarkLimits(),
            checkpoint_resolver=reject,
            runtime_loader=loader,
            probe=FakeProbe(),
            environment_reader=fake_environment,
            cache_clearer=lambda: None,
        )
    assert not loaded


def test_writable_checkpoint_stops_before_runtime_load(tmp_path: Path) -> None:
    ref = CheckpointRef(tmp_path / "model.safetensors", CHECKPOINT_SHA256, CHECKPOINT_SIZE)
    loaded = False

    def loader(_: CheckpointRef) -> object:
        nonlocal loaded
        loaded = True
        return object()

    with pytest.raises(NonRetryableProviderError, match="read-only"):
        collect_benchmark(
            BenchmarkWorkload(series_count=1, context_length=64, horizon=1),
            BenchmarkLimits(),
            checkpoint_resolver=lambda _: ref,
            runtime_loader=loader,
            probe=FakeProbe(),
            environment_reader=fake_environment,
            cache_clearer=lambda: None,
            checkpoint_read_only_reader=lambda _: False,
        )
    assert not loaded


def test_report_is_content_addressed_and_immutable(tmp_path: Path) -> None:
    report = collect(tmp_path)
    uri, checksum = publish_report(report, tmp_path / "output")
    assert len(checksum) == 64
    paths = list((tmp_path / "output" / "timesfm-benchmarks").glob("*.json"))
    assert len(paths) == 1 and paths[0].read_text(encoding="utf-8")
    same_uri, same_checksum = publish_report(report, tmp_path / "output")
    assert (same_uri, same_checksum) == (uri, checksum)


def test_cli_returns_assessment_status(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        benchmark_cli,
        "run_benchmark",
        lambda *args: {
            "benchmark_id": "b" * 64,
            "outcome": "PASSED",
            "report_uri": "file:///report.json",
            "report_sha256": "a" * 64,
        },
    )
    assert benchmark_cli.main(["--output-root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "PASSED"


def test_linux_probe_reports_process_peak_rss() -> None:
    assert SystemProcessProbe().peak_rss_bytes() > 0
