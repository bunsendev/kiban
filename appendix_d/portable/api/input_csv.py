"""Validate the synthetic P1 CSV before passing it to the existing provider."""

from io import BytesIO

import pandas as pd

from forecast_provider.frames import validate_train_frame

MAX_CSV_BYTES = 1_000_000
MAX_ROWS = 20_000
MAX_SERIES = 100


class InputError(ValueError):
    pass


def parse_csv(data: bytes) -> pd.DataFrame:
    if not data or len(data) > MAX_CSV_BYTES:
        raise InputError("CSVが空、または1 MBを超えています")
    try:
        frame = pd.read_csv(BytesIO(data), encoding="utf-8-sig", dtype={"unique_id": "string"})
    except (UnicodeError, pd.errors.ParserError, ValueError) as exc:
        raise InputError("UTF-8のCSVとして読み取れません") from exc
    if list(frame.columns) != ["ds", "unique_id", "y"]:
        raise InputError("列は ds,unique_id,y の順に指定してください")
    if frame.empty or len(frame) > MAX_ROWS:
        raise InputError("データ行数が範囲外です")
    if frame["unique_id"].isna().any() or frame["unique_id"].nunique() > MAX_SERIES:
        raise InputError("系列IDが空、または系列が多すぎます")
    try:
        frame["ds"] = pd.to_datetime(frame["ds"], format="%Y-%m-%d", errors="raise")
        frame["y"] = pd.to_numeric(frame["y"], errors="raise")
        frame["unique_id"] = frame["unique_id"].astype(str)
        validate_train_frame(frame)
    except (ValueError, TypeError) as exc:
        raise InputError("日付・数量・重複に誤りがあります") from exc
    except Exception as exc:
        from forecast_provider.errors import ContractViolationError

        if isinstance(exc, ContractViolationError):
            raise InputError("日付・数量・重複に誤りがあります") from exc
        raise
    if frame["y"].isna().any():
        raise InputError("P1人工CSVには全日付の数量を指定してください。0も有効です")
    if any(len(uid) > 80 for uid in frame["unique_id"]):
        raise InputError("系列IDが長すぎます")
    if frame.groupby("unique_id").size().min() < 7:
        raise InputError("各系列には7日以上の実績が必要です")
    if frame.groupby("unique_id")["ds"].max().nunique() != 1:
        raise InputError("各系列の最終日を揃えてください")
    return frame.sort_values(["unique_id", "ds"], kind="stable").reset_index(drop=True)
