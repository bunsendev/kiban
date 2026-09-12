"""TimesFM専用Worker運用ベンチマークCLI。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import BenchmarkLimits, BenchmarkWorkload
from .runner import run_benchmark


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="検証済みTimesFM 2.5 checkpointを人工系列で計測します"
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--series-count", type=int, default=3)
    parser.add_argument("--context-length", type=int, default=512)
    parser.add_argument("--horizon", type=int, default=15)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--measured-runs", type=int, default=3)
    parser.add_argument("--profile-name", default="cpu-timesfm")
    parser.add_argument("--cpu-limit", type=float, default=2.0)
    parser.add_argument("--memory-limit-bytes", type=int, default=4 * 1024**3)
    parser.add_argument("--max-model-initialize-seconds", type=float, default=600.0)
    parser.add_argument("--max-forecast-seconds", type=float, default=600.0)
    parser.add_argument("--max-peak-rss-bytes", type=int, default=4 * 1024**3)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workload = BenchmarkWorkload(
        series_count=args.series_count,
        context_length=args.context_length,
        horizon=args.horizon,
        warmup_runs=args.warmup_runs,
        measured_runs=args.measured_runs,
    )
    limits = BenchmarkLimits(
        profile_name=args.profile_name,
        cpu_limit=args.cpu_limit,
        memory_limit_bytes=args.memory_limit_bytes,
        max_model_initialize_seconds=args.max_model_initialize_seconds,
        max_forecast_seconds=args.max_forecast_seconds,
        max_peak_rss_bytes=args.max_peak_rss_bytes,
    )
    result = run_benchmark(workload, limits, args.output_root, args.checkpoint)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["outcome"] == "PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
