"""日次入出力契約。POINTとQUANTILEを別行で保持する。"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from numbers import Real

import numpy as np
import pandas as pd

from .contracts import (
    MEDIAN_QUANTILE,
    PREDICT_REQUIRED_COLUMNS,
    QUANTILE_DECIMALS,
    TRAIN_REQUIRED_COLUMNS,
    ForecastDataset,
)
from .errors import ContractViolationError

TARGET_KEY = ["unique_id", "origin_date", "target_date", "horizon"]
VALUE_KEY = [*TARGET_KEY, "forecast_kind", "quantile"]


def _validate_naive_datetime(series: pd.Series, name: str) -> None:
    if not pd.api.types.is_datetime64_any_dtype(series):
        raise ContractViolationError(f"{name} は datetime64 で指定します")
    if getattr(series.dtype, "tz", None) is not None or series.isna().any():
        raise ContractViolationError(f"{name} はtimezone/NaTを含められません")
    if not series.eq(series.dt.normalize()).all():
        raise ContractViolationError(f"{name} は日単位（00:00）で指定します")


def _validate_string_ids(series: pd.Series, name: str = "unique_id") -> None:
    if series.isna().any() or not series.map(lambda v: isinstance(v, str) and bool(v)).all():
        raise ContractViolationError(f"{name} は空でない文字列で指定します")


def _numeric(series: pd.Series, name: str, allow_nan: bool = False) -> None:
    if (
        pd.api.types.is_bool_dtype(series)
        or pd.api.types.is_complex_dtype(series)
        or not pd.api.types.is_numeric_dtype(series)
    ):
        raise ContractViolationError(f"{name} は実数で指定します")
    if not allow_nan and series.isna().any():
        raise ContractViolationError(f"{name} に欠損は指定できません")
    if not np.isfinite(series.dropna().to_numpy(dtype=float)).all():
        raise ContractViolationError(f"{name} に無限大は指定できません")


def validate_train_frame(frame: pd.DataFrame) -> None:
    if not set(TRAIN_REQUIRED_COLUMNS).issubset(frame.columns) or not frame.columns.is_unique:
        raise ContractViolationError("学習・履歴の必須列不足または列重複")
    _validate_string_ids(frame.unique_id)
    _validate_naive_datetime(frame.ds, "ds")
    _numeric(frame.y, "y", allow_nan=True)
    if frame.y.dropna().lt(0).any():
        raise ContractViolationError("返品・取消を分離してから非負出荷数量を渡します")
    if frame.duplicated(["unique_id", "ds"]).any():
        raise ContractViolationError("商品・日付の重複")


def normalize_train_frame(frame: pd.DataFrame) -> pd.DataFrame:
    validate_train_frame(frame)
    out = frame.sort_values(["unique_id", "ds"], kind="stable").reset_index(drop=True).copy()
    out["y"] = out.y.astype(float)
    return out


def validate_fit_frame(train_df: pd.DataFrame, dataset: ForecastDataset) -> pd.DataFrame:
    frame = normalize_train_frame(train_df)
    if not frame.empty and (
        frame.ds.min().date() < dataset.train_start or frame.ds.max().date() > dataset.train_end
    ):
        raise ContractViolationError("TRAIN期間外の学習実績")
    return frame


def validate_history_frame(history: pd.DataFrame, origin_date: date) -> pd.DataFrame:
    frame = normalize_train_frame(history)
    if not frame.empty and frame.ds.max().date() > origin_date:
        raise ContractViolationError("起点より未来の履歴")
    return frame


def validate_future_frame(
    frame: pd.DataFrame,
    *,
    unique_ids: set[str] | None = None,
    max_horizon: int = 400,
    origin_date: date | None = None,
    horizons: set[int] | None = None,
    allowed_extra_columns: set[str] | None = None,
) -> None:
    if not set(TARGET_KEY).issubset(frame.columns) or not frame.columns.is_unique:
        raise ContractViolationError("予測対象の必須列不足または列重複")
    if "y" in frame.columns:
        raise ContractViolationError("予測対象に実績yを含められません")
    allowed = set(TARGET_KEY) | set(allowed_extra_columns or ())
    extras = sorted(set(frame.columns) - allowed)
    if extras:
        raise ContractViolationError(f"予測対象に未許可列が含まれます: {extras}")
    _validate_string_ids(frame.unique_id)
    for col in ("origin_date", "target_date"):
        _validate_naive_datetime(frame[col], col)
    h = frame.horizon
    if h.isna().any() or pd.api.types.is_bool_dtype(h) or not pd.api.types.is_integer_dtype(h):
        raise ContractViolationError("horizonはbool以外の整数型で指定します")
    if not h.between(1, max_horizon).all():
        raise ContractViolationError("horizonが対応範囲外")
    if not (frame.target_date - frame.origin_date).eq(pd.to_timedelta(h, unit="D")).all():
        raise ContractViolationError("対象日とhorizonの不一致")
    if frame.duplicated(TARGET_KEY).any():
        raise ContractViolationError("予測対象キー重複")
    if unique_ids is not None and not set(frame.unique_id).issubset(unique_ids):
        raise ContractViolationError("dataset外の系列")
    if origin_date is not None and not frame.origin_date.eq(pd.Timestamp(origin_date)).all():
        raise ContractViolationError("起点不一致")
    if horizons is not None and not set(h).issubset(horizons):
        raise ContractViolationError("要求horizons外の予測対象")


def validate_predict_frame(
    result: pd.DataFrame,
    *,
    expected_quantiles: set[float] | None = None,
    expected_targets: pd.DataFrame | None = None,
    allow_empty: bool = False,
) -> None:
    """型検証と要求照合。保存時はreconcile_predictionsで全予定を照合する。"""
    if not set(PREDICT_REQUIRED_COLUMNS).issubset(result.columns) or not result.columns.is_unique:
        raise ContractViolationError("予測出力の必須列不足または列重複")
    if result.empty:
        if not allow_empty or (expected_targets is not None and not expected_targets.empty):
            raise ContractViolationError("予測出力が空です")
        return
    keys = result[TARGET_KEY].drop_duplicates()
    validate_future_frame(keys)
    if expected_targets is not None:
        validate_future_frame(expected_targets[TARGET_KEY])
        joined = keys.merge(
            expected_targets[TARGET_KEY], on=TARGET_KEY, how="outer", indicator=True
        )
        if not joined._merge.eq("both").all():
            raise ContractViolationError("予測対象の不足または余分があります")
    if not result.forecast_kind.isin(["POINT", "QUANTILE"]).all():
        raise ContractViolationError("forecast_kindはPOINT/QUANTILEのみ")
    point = result[result.forecast_kind.eq("POINT")]
    quant = result[result.forecast_kind.eq("QUANTILE")]
    if point["quantile"].notna().any():
        raise ContractViolationError("POINTのquantileはNULLです")
    if point.duplicated(TARGET_KEY).any() or len(point) != len(keys):
        raise ContractViolationError("各対象にPOINTが1行必要です")
    if not quant.empty:
        _numeric(quant["quantile"], "quantile")
        if not ((quant["quantile"] > 0) & (quant["quantile"] < 1)).all():
            raise ContractViolationError("quantileは0と1の間です")
        if not quant["quantile"].eq(quant["quantile"].round(QUANTILE_DECIMALS)).all():
            raise ContractViolationError("quantileの桁数超過")
    if result.duplicated(VALUE_KEY).any():
        raise ContractViolationError("予測出力キー重複")
    for col in ("yhat_raw", "yhat"):
        _numeric(result[col], col)
    if not (result.yhat - result.yhat_raw.clip(lower=0)).abs().le(1e-9).all():
        raise ContractViolationError("yhatはmax(0,yhat_raw)です")
    for _, group in result.groupby(TARGET_KEY, sort=False):
        q = group[group.forecast_kind.eq("QUANTILE")].sort_values("quantile")
        if expected_quantiles is not None and set(q["quantile"]) != expected_quantiles:
            raise ContractViolationError("要求quantileの不足または余分")
        if np.any(np.diff(q.yhat_raw.to_numpy(dtype=float)) < -1e-9):
            raise ContractViolationError("quantile crossing")


def quantiles_from_interval_levels(levels: tuple[float, ...]) -> list[float]:
    """区間水準（0.8, 0.95など）をquantile一覧へ変換する。

    丸め桁数は QUANTILE_DECIMALS（=6）で、forecast_values.quantile の
    NUMERIC(8,6) と一致させる。数値以外、bool、非有限値、重複水準、
    および丸め後に別水準と同じquantile端点へ潰れる指定は拒否する。
    """
    if not isinstance(levels, (tuple, list)):
        raise ContractViolationError("区間水準は配列で指定します")
    if not levels:
        return []
    qs = {MEDIAN_QUANTILE}
    seen_levels: set[float] = set()
    seen_pairs: dict[tuple[float, float], float] = {}
    quantum = Decimal(1).scaleb(-QUANTILE_DECIMALS)

    for raw_level in levels:
        if isinstance(raw_level, bool) or not isinstance(raw_level, Real):
            raise ContractViolationError(f"区間水準はbool以外の数値で指定します: {raw_level!r}")
        level = float(raw_level)
        if not np.isfinite(level) or not 0.0 < level < 1.0:
            raise ContractViolationError(f"区間水準は0〜1の範囲で指定します: {level}")
        if level in seen_levels:
            raise ContractViolationError(f"区間水準が重複しています: {level}")
        seen_levels.add(level)

        level_dec = Decimal(str(level))
        tail_dec = (Decimal("1") - level_dec) / Decimal("2")
        low = float(tail_dec.quantize(quantum, rounding=ROUND_HALF_UP))
        high = float((Decimal("1") - tail_dec).quantize(quantum, rounding=ROUND_HALF_UP))

        if not 0.0 < low < 1.0 or not 0.0 < high < 1.0:
            raise ContractViolationError(
                f"区間水準 {level} は小数{QUANTILE_DECIMALS}桁へ丸めると "
                f"{low}/{high} となり、quantile の値域を外れます。"
                "より内側の水準を指定してください"
            )
        if low >= high:
            raise ContractViolationError(
                f"区間水準 {level} は小数{QUANTILE_DECIMALS}桁へ丸めると "
                f"上下端が区別できません（{low}/{high}）"
            )
        if low == MEDIAN_QUANTILE or high == MEDIAN_QUANTILE:
            raise ContractViolationError(f"区間水準 {level} の端点が中央値の quantile と重複します")

        # 丸めによって実現水準が要求水準からずれる指定を拒否する。
        # 通す場合、実験定義には要求水準が残り、保存される予測値は別水準の
        # 区間になるため、Coverage がどの水準に対する被覆か判別できなくなる。
        realized = Decimal(str(high)) - Decimal(str(low))
        if realized != level_dec:
            raise ContractViolationError(
                f"区間水準 {level} は小数{QUANTILE_DECIMALS}桁へ丸めると "
                f"実現水準が {realized} になります。"
                f"丸めても水準が変わらない値を指定してください"
            )

        pair = (low, high)
        if pair in seen_pairs:
            raise ContractViolationError(
                f"区間水準 {level} は小数{QUANTILE_DECIMALS}桁へ丸めると "
                f"区間水準 {seen_pairs[pair]} と同じ端点 {pair} になります"
            )
        seen_pairs[pair] = level
        qs.add(low)
        qs.add(high)

    return sorted(qs)
