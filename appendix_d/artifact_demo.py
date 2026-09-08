"""人工データのモデル/起点履歴を保存し、別プロセスで同じ予測を再現する。"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from forecast_provider import ForecastDataset, ProviderConfig, RunContext
from forecast_provider.artifacts import ArtifactRef, ForecastArtifactRepository, LocalArtifactStore
from forecast_provider.providers.baseline_codec import BuiltinBaselineCodec
from forecast_provider.providers.builtin_baseline import BuiltinBaselineProvider
from forecast_provider.run_context import cutoff_for_origin


def example(output: Path):
    dataset = ForecastDataset(
        "artifact-demo-snapshot-v1",
        "selection-v1",
        ("A", "B"),
        date(2024, 1, 1),
        date(2025, 12, 31),
        date(2026, 1, 1),
        date(2026, 1, 20),
        10,
        15,
        10,
    )
    config = ProviderConfig(
        "builtin-baseline",
        "moving_average_28",
        preprocessing_version="daily-nan-preserving-v1",
        interval_levels=(0.8,),
    )
    context = RunContext(
        "artifact-demo-run",
        "artifact-demo-experiment",
        42,
        datetime.now(UTC) + timedelta(hours=1),
        output,
        output,
        "cpu",
        logging.getLogger("artifact"),
        availability_mode="ASSUMED",
        cutoff_at=cutoff_for_origin(dataset.train_end),
    ).for_origin(date(2026, 1, 10))
    future = pd.DataFrame(
        [
            (
                uid,
                pd.Timestamp(context.origin_date),
                pd.Timestamp(context.origin_date) + pd.Timedelta(days=h),
                h,
            )
            for uid in dataset.unique_ids
            for h in (1, 7, 10)
        ],
        columns=["unique_id", "origin_date", "target_date", "horizon"],
    )
    repository = ForecastArtifactRepository(
        LocalArtifactStore(output / "objects"), [BuiltinBaselineCodec()]
    )
    return dataset, config, context, future, repository


def save(output: Path) -> None:
    ds, config, ctx, future, repo = example(output)
    dates = pd.date_range(ds.train_start, ctx.origin_date)
    data = pd.concat(
        [
            pd.DataFrame(
                {"unique_id": uid, "ds": dates, "y": np.arange(len(dates), dtype=float) % 17 + i}
            )
            for i, uid in enumerate(ds.unique_ids)
        ],
        ignore_index=True,
    )
    data.loc[data.ds.eq(pd.Timestamp("2025-12-30")), "y"] = np.nan
    provider = BuiltinBaselineProvider()
    fit_context = ctx.for_origin(ds.train_end)
    model = provider.fit_parameters(
        data[data.ds.le(pd.Timestamp(ds.train_end))], ds, config, fit_context
    )
    history = provider.refresh_context(model, data, ctx.origin_date, ctx)
    expected = provider.predict(model, history, future, [1, 7, 10], ctx)
    model_artifact = repo.save_model(model, ds, config, fit_context)
    context_artifact = repo.save_context(history, model_artifact, ds, config, ctx)
    (output / "references.json").write_text(
        json.dumps(
            {"model": model_artifact.to_dict(), "context": context_artifact.to_dict()}, indent=2
        ),
        encoding="utf-8",
        newline="\n",
    )
    expected.to_csv(output / "expected.csv", index=False)
    provider.cleanup(ctx)


def restore(output: Path) -> None:
    ds, config, ctx, future, repo = example(output)
    refs = json.loads((output / "references.json").read_text(encoding="utf-8"))
    model_artifact = ArtifactRef.from_dict(refs["model"])
    model = repo.load_model(model_artifact, ds, config, ctx.for_origin(ds.train_end))
    history = repo.load_context(
        ArtifactRef.from_dict(refs["context"]), model_artifact, ds, config, ctx
    )
    provider = BuiltinBaselineProvider()
    actual = provider.predict(model, history, future, [1, 7, 10], ctx)
    expected = pd.read_csv(
        output / "expected.csv",
        parse_dates=["origin_date", "target_date"],
        float_precision="round_trip",
    )
    pd.testing.assert_frame_equal(expected, actual, check_exact=True)
    actual.to_csv(output / "restored.csv", index=False)
    provider.cleanup(ctx)
    print(f"Restored without fit: {len(actual)} rows; exact POINT/QUANTILE match")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("save", "restore", "verify"), nargs="?", default="verify"
    )
    parser.add_argument("--output", type=Path, default=Path("artifact_output"))
    args = parser.parse_args()
    output = args.output.resolve()
    if args.action in ("save", "verify"):
        save(output)
    if args.action == "restore":
        restore(output)
    elif args.action == "verify":
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "restore", "--output", str(output)],
            check=True,
        )


if __name__ == "__main__":
    main()
