"""決定的なカレンダー列と、known_atで版選択する将来変数を区別する。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .errors import ContractViolationError
from .frames import TARGET_KEY, validate_future_frame

CALENDAR_COLUMNS = frozenset(
    {"calendar_dayofweek", "calendar_month", "calendar_day", "calendar_is_month_start"}
)
VERSION_COLUMNS = ["unique_id", "ds", "feature", "value", "known_at"]


def validate_feature_versions(versions: pd.DataFrame) -> None:
    if not versions.columns.is_unique or not set(VERSION_COLUMNS).issubset(versions.columns):
        raise ContractViolationError("将来変数版はunique_id/ds/feature/value/known_atが必要です")
    for col in ("unique_id", "feature"):
        if (
            versions[col].isna().any()
            or not versions[col].map(lambda x: isinstance(x, str) and bool(x)).all()
        ):
            raise ContractViolationError("将来変数版の識別子が不正です")
    ds = versions.ds
    if (
        not pd.api.types.is_datetime64_any_dtype(ds)
        or ds.isna().any()
        or getattr(ds.dtype, "tz", None) is not None
        or not ds.eq(ds.dt.normalize()).all()
    ):
        raise ContractViolationError("将来変数dsはtimezoneなしの日単位です")
    known = versions.known_at
    if (
        not pd.api.types.is_datetime64_any_dtype(known)
        or known.isna().any()
        or getattr(known.dtype, "tz", None) is None
    ):
        raise ContractViolationError("known_atはtimezone付きの確定・変更日時です")
    if versions.duplicated(["unique_id", "ds", "feature", "known_at"]).any():
        raise ContractViolationError("同じ確定時刻の将来変数版が重複しています")
    if versions.feature.isin(CALENDAR_COLUMNS).any():
        raise ContractViolationError("固定カレンダーを外部値で上書きできません")
    values = versions.value
    if (
        not pd.api.types.is_numeric_dtype(values)
        or pd.api.types.is_bool_dtype(values)
        or pd.api.types.is_complex_dtype(values)
        or values.isna().any()
        or not np.isfinite(values.to_numpy(dtype=float)).all()
    ):
        raise ContractViolationError("将来変数valueは非欠損の有限実数です")


def attach_features(
    targets: pd.DataFrame,
    columns: tuple[str, ...],
    *,
    versions: pd.DataFrame | None = None,
    allow_history: bool = False,
) -> pd.DataFrame:
    """起点翌日00:00 JST以前に既知の最新版だけを対象ごとに選ぶ。

    allow_historyはrunnerが検証済み履歴を渡す内部用。既知版なしは契約違反。
    生の最終確定データの列名を登録するだけでは既知の将来変数として使えない。
    """
    if not allow_history:
        validate_future_frame(targets)
    out = targets.copy()
    if not columns:
        return out
    dynamic = set(columns) - CALENDAR_COLUMNS
    if dynamic:
        if versions is None:
            raise ContractViolationError("変更される将来変数にはknown_at付き版テーブルが必要です")
        validate_feature_versions(versions)
    for column in columns:
        dates = out.target_date.dt
        if column == "calendar_dayofweek":
            out[column] = dates.dayofweek
        elif column == "calendar_month":
            out[column] = dates.month
        elif column == "calendar_day":
            out[column] = dates.day
        elif column == "calendar_is_month_start":
            out[column] = dates.is_month_start.astype(int)
        else:
            source = versions[versions.feature.eq(column)].rename(columns={"ds": "target_date"})
            indexed = out[TARGET_KEY].reset_index(drop=True).assign(_row=np.arange(len(out)))
            candidates = indexed.merge(
                source[["unique_id", "target_date", "value", "known_at"]],
                on=["unique_id", "target_date"],
                how="left",
            )
            cutoff = (candidates.origin_date + pd.Timedelta(days=1)).dt.tz_localize("Asia/Tokyo")
            candidates = candidates[candidates.known_at.le(cutoff)]
            selected = (
                candidates.sort_values("known_at")
                .drop_duplicates("_row", keep="last")
                .set_index("_row")
                .value.reindex(range(len(out)))
            )
            if selected.isna().any():
                raise ContractViolationError(f"{column}: 起点で既知の値がない対象日があります")
            out[column] = selected.to_numpy()
    return out
