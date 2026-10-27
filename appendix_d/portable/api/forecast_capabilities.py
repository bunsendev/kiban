"""A narrow, explicit NaN-preserving capability, not a blanket missing-data waiver."""

import math

import pandas as pd

from forecast_provider.providers.baseline_algorithms import point_forecast
from forecast_provider.providers.builtin_baseline import PROVIDER_VERSION

CAPABILITY = "portable-missing-seasonal7-v1:" + PROVIDER_VERSION


def missing_capability(frame, origin, model="seasonal_naive_7", horizon=14):
    if model != "seasonal_naive_7":
        return {"supported": False, "reason": "この実行モデルは欠損を残す方式に未対応です"}
    series = frame.set_index("ds")["y"].sort_index()
    series = series.loc[series.index <= pd.Timestamp(origin)]
    if series.notna().sum() < 7:
        return {"supported": False, "reason": "確認済み実績がモデルの最小7日未満です"}
    for h in range(1, horizon + 1):
        target = pd.Timestamp(origin) + pd.Timedelta(days=h)
        value = point_forecast(series, target, h, model)
        if value is None or not math.isfinite(value) or value < 0:
            return {"supported": False, "reason": f"{target.date()}の同曜日実績が不足しています"}
    return {"supported": True, "reason": "欠損はNaNで維持し、過去の同曜日を使う暫定予測です"}
