"""Phase 1Aの統合試験用。全系列・全originを持つ小さな人工データ。"""

from dataclasses import replace

import pandas as pd
import pytest
from test_builtin_baseline import make_context, make_dataset

from forecast_provider import ProviderConfig


@pytest.fixture
def phase1a_case():
    dataset = replace(make_dataset(("A", "B")), test_end=pd.Timestamp("2026-01-21").date())
    data = pd.DataFrame(
        [
            (uid, day, float(day.day + i))
            for i, uid in enumerate(dataset.unique_ids)
            for day in pd.date_range("2024-01-01", "2026-01-21")
        ],
        columns=["unique_id", "ds", "y"],
    )
    config = ProviderConfig(
        "builtin-baseline",
        "moving_average_28",
        preprocessing_version="daily-nan-preserving-v1",
    )
    return data, dataset, config, make_context()
