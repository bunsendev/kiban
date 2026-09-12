"""学習・起点履歴を未来参照なしで日次系列へ整形する。"""

from __future__ import annotations

from datetime import date

import pandas as pd


def prepare_daily_series(
    group: pd.DataFrame, start: date, end: date
) -> tuple[pd.Series, int, int]:
    """指定期間を日次化し、過去方向だけから補完する。先頭欠損は除く。"""
    index = pd.date_range(start, end, freq="D")
    source = group.set_index("ds")["y"].astype("float64").reindex(index)
    actual_count = int(source.notna().sum())
    filled = source.ffill().dropna().astype("float64")
    filled.name = "y"
    filled.index.name = "ds"
    imputed_count = int(len(filled) - source.loc[filled.index].notna().sum())
    return filled, actual_count, imputed_count
