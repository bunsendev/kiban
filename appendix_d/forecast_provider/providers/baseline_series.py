"""baselineの日次float64 SeriesをNaN/0を区別してJSON化する。"""

import numpy as np
import pandas as pd

from ..artifacts import json_format as jf
from ..artifacts.contracts import ArtifactError


def encode_series(series: pd.Series) -> dict:
    if not isinstance(series, pd.Series) or series.dtype != np.dtype("float64") or series.empty:
        raise ArtifactError("baseline seriesは非空float64です")
    index = series.index
    if not isinstance(index, pd.DatetimeIndex) or index.tz is not None or index.hasnans:
        raise ArtifactError("baseline series日付indexが不正です")
    expected = pd.date_range(index[0], periods=len(index), freq="D")
    if not index.equals(expected) or index[0].time().isoformat() != "00:00:00":
        raise ArtifactError("baseline seriesは連続した日単位です")
    if any(name is not None and not isinstance(name, str) for name in (series.name, index.name)):
        raise ArtifactError("baseline seriesの名前は文字列またはNoneです")
    values = series.to_numpy()
    if np.isinf(values).any() or (values < 0).any():
        raise ArtifactError("baseline seriesは非負値またはNaNです")
    return {
        "start": index[0].date().isoformat(),
        "name": series.name,
        "index_name": index.name,
        "values": [None if np.isnan(value) else float(value) for value in values],
    }


def decode_series(value: dict) -> pd.Series:
    jf.keys(value, {"start", "name", "index_name", "values"})
    start = jf.day(value["start"])
    if not isinstance(value["values"], list) or not value["values"]:
        raise ArtifactError("baseline seriesの値配列が不正です")
    if any(value[k] is not None and not isinstance(value[k], str) for k in ("name", "index_name")):
        raise ArtifactError("baseline seriesの名前が不正です")
    values = [np.nan if x is None else jf.number(x) for x in value["values"]]
    if any(x < 0 for x in values):
        raise ArtifactError("baseline seriesの負数量")
    try:
        index = pd.date_range(start, periods=len(values), freq="D", name=value["index_name"])
        return pd.Series(values, index=index, dtype="float64", name=value["name"])
    except (ValueError, OverflowError) as exc:
        raise ArtifactError("baseline seriesの日付範囲が不正です") from exc


def encode_series_map(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ArtifactError("baseline series集合が不正です")
    checked = {jf.text(uid): series for uid, series in value.items()}
    return {uid: encode_series(series) for uid, series in sorted(checked.items())}


def decode_series_map(value: dict) -> dict[str, pd.Series]:
    if not isinstance(value, dict):
        raise ArtifactError("baseline series集合が不正です")
    return {jf.text(uid): decode_series(series) for uid, series in value.items()}
