"""段階D規模の通し実行。仕様書6.1・6.2・8.1の数値を実測で確認する。"""

import logging
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forecast_provider import ForecastDataset, ProviderConfig, RunContext, registry
from forecast_provider.frames import validate_predict_frame

rng = np.random.default_rng(1)
dow = np.array([1.3, 1.0, 0.9, 1.0, 1.2, 0.6, 0.2])
days = pd.date_range("2023-01-01", periods=1096, freq="D")
big = pd.concat(
    [
        pd.DataFrame(
            {
                "unique_id": f"P{i:03d}__{'KAZO' if i % 2 else 'KOBE'}",
                "ds": days,
                "y": np.maximum(
                    0,
                    (80 + i) * dow[days.dayofweek]
                    + np.linspace(0, 20, 1096)
                    + rng.normal(0, 6, 1096),
                ).round(0),
            }
        )
        for i in range(100)
    ],
    ignore_index=True,
)

dataset = ForecastDataset(
    dataset_snapshot_id="dss_scale",
    selection_version="sel_scale",
    unique_ids=tuple(sorted(big["unique_id"].unique())),
    train_start=date(2023, 1, 1),
    train_end=date(2024, 12, 31),
    test_start=date(2025, 1, 1),
    test_end=date(2025, 12, 31),
    origin_interval_days=10,
    max_horizon=15,
    primary_horizon_max=10,
)

tmp = Path(tempfile.mkdtemp())
ctx = RunContext(
    "run_scale",
    "exp_scale",
    42,
    datetime.now(UTC) + timedelta(hours=2),
    tmp,
    tmp,
    "cpu-standard",
    logging.getLogger("scale"),
)
provider = registry.create("builtin-baseline")
config = ProviderConfig("builtin-baseline", "seasonal_naive_7", interval_levels=(0.8,))

model_ref = provider.fit_parameters(
    big[big["ds"] <= pd.Timestamp(dataset.train_end)], dataset, config, ctx
)
uids = sorted(big["unique_id"].unique())
outs = []
for origin in dataset.origin_dates():
    ot = pd.Timestamp(origin)
    cref = provider.refresh_context(model_ref, big[big["ds"] <= ot], origin, ctx)
    future = pd.DataFrame(
        [
            {
                "unique_id": u,
                "origin_date": ot,
                "target_date": ot + pd.Timedelta(days=h),
                "horizon": h,
            }
            for u in uids
            for h in range(1, dataset.max_horizon + 1)
        ]
    )
    future = future[future["target_date"] <= pd.Timestamp(dataset.test_end)]
    outs.append(provider.predict(model_ref, cref, future, list(range(1, 16)), ctx))

res = pd.concat(outs, ignore_index=True)
validate_predict_frame(res)
point = res[res["forecast_kind"] == "POINT"]
primary = (
    point[point["horizon"] <= dataset.primary_horizon_max]
    .sort_values("origin_date")
    .groupby(["unique_id", "target_date"], as_index=False)
    .tail(1)
)
print(f"予測起点数            : {len(dataset.origin_dates())}")
print(f"通期評価の成立        : {dataset.full_period_evaluation_valid}")
print(f"評価プロファイル      : {dataset.evaluation_profile}")
print(f"点予測行数（1OSS）    : {len(point):,}")
print(f"POINT＋QUANTILE行数        : {len(res):,}")
print(f"通期評価 対象日／系列 : {primary.groupby('unique_id').size().unique()}")
print(f"通期評価 重複件数     : {primary.duplicated(['unique_id', 'target_date']).sum()}")
