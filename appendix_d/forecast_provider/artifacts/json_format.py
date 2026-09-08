"""実行可能オブジェクトを含めない、厳密な版付きJSON用の基本検証。"""

import json
import math
from datetime import UTC, date, datetime

from .contracts import ArtifactError


def keys(value, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ArtifactError("artifactフィールド不一致")


def text(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactError("artifact識別子は空でない文字列です")
    return value


def integer(value, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ArtifactError("artifact整数が不正です")
    return value


def number(value) -> float:
    if type(value) not in (int, float):
        raise ArtifactError("artifact数値が不正です")
    try:
        out = float(value)
    except OverflowError as exc:
        raise ArtifactError("artifact数値が範囲外です") from exc
    if not math.isfinite(out):
        raise ArtifactError("artifact数値は有限値です")
    return out


def day(value) -> date:
    try:
        result = date.fromisoformat(text(value))
        if result.isoformat() != value:
            raise ValueError("noncanonical date")
        return result
    except (TypeError, ValueError) as exc:
        raise ArtifactError("artifact日付はYYYY-MM-DDです") from exc


def instant(value) -> datetime:
    try:
        result = datetime.fromisoformat(text(value))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("naive datetime")
        return result.astimezone(UTC)
    except (TypeError, ValueError) as exc:
        raise ArtifactError("artifact時刻はtimezone付きISO日時です") from exc


def unique_strings(value) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ArtifactError("artifact文字列配列が不正です")
    result = tuple(text(item) for item in value)
    if len(result) != len(set(result)):
        raise ArtifactError("artifact文字列配列の重複")
    return result


def dumps(value: dict) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ArtifactError("artifactをJSONへ変換できません") from exc


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactError("artifact JSONの重複キー")
        result[key] = value
    return result


def _constant(value):
    raise ArtifactError(f"artifact JSONの非有限値: {value}")


def loads(data: bytes) -> dict:
    try:
        result = json.loads(
            data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ArtifactError("artifact JSONを解釈できません") from exc
    if not isinstance(result, dict):
        raise ArtifactError("artifact JSONのルートはobjectです")
    return result
