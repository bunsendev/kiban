"""Adapter from the P1 CSV to the repository's builtin-baseline provider."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from forecast_provider import ForecastDataset, ProviderConfig, RunContext, registry
from forecast_provider.frames import validate_predict_frame
from forecast_provider.run_context import cutoff_for_origin

from .input_csv import InputError

MODEL = "seasonal_naive_7"
HORIZON = 7


def forecast(frame: pd.DataFrame, work_dir: Path, run_id: str) -> list[dict]:
    origin = frame["ds"].max().date()
    ids = tuple(sorted(frame["unique_id"].unique()))
    dataset = ForecastDataset(
        dataset_snapshot_id="portable-p1",
        selection_version="portable-p1",
        unique_ids=ids,
        train_start=frame["ds"].min().date(),
        train_end=origin,
        test_start=origin + timedelta(days=1),
        test_end=origin + timedelta(days=HORIZON),
        origin_interval_days=HORIZON,
        max_horizon=HORIZON,
        primary_horizon_max=HORIZON,
        report_horizons=(HORIZON,),
    )
    config = ProviderConfig(
        provider_id="builtin-baseline",
        model=MODEL,
        preprocessing_version="daily-nan-preserving-v1",
        interval_levels=(),
    )
    provider = registry.create("builtin-baseline")
    validation = provider.validate(dataset, config)
    if not validation.ok:
        raise InputError("Baselineの入力条件を満たしません")
    context = RunContext(
        run_id=run_id,
        experiment_id="portable-p1",
        seed=42,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        input_dir=work_dir,
        output_dir=work_dir,
        resource_profile="portable-p1",
        logger=logging.getLogger("portable.baseline"),
        availability_mode="ASSUMED",
        cutoff_at=cutoff_for_origin(origin),
        origin_date=origin,
    )
    model_ref = provider.fit_parameters(frame, dataset, config, context)
    context_ref = provider.refresh_context(model_ref, frame, origin, context)
    future = pd.DataFrame(
        [
            {
                "unique_id": uid,
                "origin_date": pd.Timestamp(origin),
                "target_date": pd.Timestamp(origin + timedelta(days=h)),
                "horizon": h,
            }
            for uid in ids
            for h in range(1, HORIZON + 1)
        ]
    )
    predicted = provider.predict(
        model_ref, context_ref, future, list(range(1, HORIZON + 1)), context
    )
    validate_predict_frame(predicted, expected_targets=future)
    point = predicted[predicted["forecast_kind"] == "POINT"].sort_values(
        ["unique_id", "target_date"], kind="stable"
    )
    return [
        {
            "unique_id": row.unique_id,
            "target_date": row.target_date.date().isoformat(),
            "horizon": int(row.horizon),
            "yhat": float(row.yhat),
        }
        for row in point.itertuples(index=False)
    ]
