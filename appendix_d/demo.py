"""人工データ3品目・3年で点予測2方式を比較する。ネットワーク接続不要。"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from forecast_provider import ForecastDataset, ProviderConfig, RunContext
from forecast_provider.evaluation import compare_runs, cumulative_evaluation
from forecast_provider.runner import run_fixed_baseline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("demo_output"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2023-01-01", "2025-12-31")
    data = pd.concat(
        [
            pd.DataFrame(
                {
                    "unique_id": uid,
                    "ds": dates,
                    "y": (100 + i * 20 + dates.dayofweek * 5 + np.arange(len(dates)) * 0.01).round(
                        0
                    ),
                }
            )
            for i, uid in enumerate(("P01_KAZO", "P01_KOBE", "P02_KAZO"))
        ],
        ignore_index=True,
    )
    ds = ForecastDataset(
        "synthetic_v1",
        "selection_v1",
        tuple(data.unique_id.unique()),
        date(2023, 1, 1),
        date(2024, 12, 31),
        date(2025, 1, 1),
        date(2025, 12, 31),
        10,
        15,
        10,
    )
    outputs, runs = {}, {}
    for model in ("seasonal_naive_7", "moving_average_28"):
        ctx = RunContext(
            model,
            "demo",
            42,
            datetime.now(UTC) + timedelta(hours=1),
            args.output,
            args.output,
            "cpu",
            logging.getLogger("demo"),
        )
        run = run_fixed_baseline(
            data, ds, ProviderConfig("builtin-baseline", model), ctx, availability_mode="ASSUMED"
        )
        outputs[model] = run["predictions"]
        runs[model] = ds
        run["predictions"].to_csv(args.output / f"{model}_predictions.csv", index=False)
        run["ledger"].to_csv(args.output / f"{model}_ledger.csv", index=False)
        cumulative_evaluation(run["ledger"], data, 15).to_csv(
            args.output / f"{model}_15day.csv", index=False
        )
    comparison = compare_runs(
        runs, outputs, data, truth_version="synthetic_truth_v1", mode="primary"
    )
    comparison["availability_mode"] = "ASSUMED"
    comparison["data_kind"] = "SYNTHETIC_NOT_BUNSEN_ACTUAL"
    payload = json.dumps(comparison, ensure_ascii=False, indent=2, allow_nan=False)
    (args.output / "comparison.json").write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
