"""日次build時点で利用可能だった休業日だけを選ぶ。"""

from datetime import UTC, datetime

from .contracts import ClosedDay


def known_closed_days(values: list[ClosedDay], as_of: str) -> list[ClosedDay]:
    cutoff = _time(as_of)
    return [value for value in values if _time(value.available_at) <= cutoff]


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("休業日のavailable_atとas_ofはtimezone付き日時です")
    return parsed.astimezone(UTC)
