"""完全性・取扱期間・休業日から日次状態を決定する。"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from .contracts import ClosedDay, DailyValue, FileCompleteness
from .domain import series_id


def decide_daily_values(
    build_id: str,
    selected_series: list[dict],
    start: date,
    end: date,
    completeness: list[FileCompleteness],
    aggregates: dict[tuple[str, str, date], dict],
    handling_periods: list[dict],
    closed_days: list[ClosedDay],
    as_of: str,
    availability_mode: str,
) -> list[DailyValue]:
    complete_by_day = {
        (item.center_id, date.fromisoformat(item.target_date)): item for item in completeness
    }
    closures = {
        (item.center_id, date.fromisoformat(item.closed_date)): item for item in closed_days
    }
    as_of_utc = datetime.fromisoformat(as_of).astimezone(UTC).isoformat()
    values = []
    for selected in selected_series:
        product_id = selected["canonical_product_id"]
        center_id = selected["center_id"]
        unique_id = series_id(product_id, center_id)
        for target in _dates(start, end):
            raw = aggregates.get((product_id, center_id, target))
            file_state = complete_by_day.get((center_id, target))
            handled = _handled(product_id, center_id, target, handling_periods)
            closure = closures.get((center_id, target))
            state, y, issue = _state(handled, closure is not None, raw, file_state)
            available_at = _availability(state, raw, file_state, closure, as_of_utc)
            if availability_mode == "OBSERVED" and raw is not None and raw["available_at"] is None:
                raise ValueError("OBSERVEDの実績にはavailable_atが必要です")
            values.append(
                DailyValue(
                    build_id,
                    product_id,
                    center_id,
                    target.isoformat(),
                    unique_id,
                    None if raw is None else raw["raw_quantity"],
                    y,
                    state,
                    available_at,
                    issue,
                )
            )
    return values


def _state(handled, closed, raw, file_state):
    quantity = None if raw is None else raw["raw_quantity"]
    if not handled:
        if raw is not None:
            return "PARTIAL_OR_INVALID", None, "SHIPMENT_OUTSIDE_HANDLING_PERIOD"
        return "NOT_HANDLED", None, None
    if closed:
        if raw is not None:
            if file_state is not None and file_state.status == "COMPLETE":
                return "OBSERVED", quantity, "SHIPMENT_ON_CLOSED_DAY"
            return "PARTIAL_OR_INVALID", None, "INCOMPLETE_FILES_WITH_SHIPMENT_ON_CLOSED_DAY"
        return "CLOSED", Decimal(0), None
    if raw is not None:
        if file_state is not None and file_state.status == "COMPLETE":
            return "OBSERVED", quantity, None
        return "PARTIAL_OR_INVALID", None, "INCOMPLETE_FILES_WITH_SHIPMENT"
    if file_state is not None and file_state.status == "COMPLETE" and file_state.zero_confirmable:
        return "CONFIRMED_ZERO", Decimal(0), None
    if file_state is not None and file_state.status == "PARTIAL_OR_INVALID":
        return "PARTIAL_OR_INVALID", None, "FILES_PARTIAL_OR_INVALID"
    return "MISSING", None, None


def _availability(state, raw, file_state, closure, as_of):
    if state == "CONFIRMED_ZERO" and file_state is not None:
        return file_state.available_at
    if state == "CLOSED" and closure is not None:
        return closure.available_at
    if raw is None or raw["available_at"] is None:
        return as_of
    if state == "OBSERVED" and file_state is not None and file_state.status == "COMPLETE":
        return (
            max(
                datetime.fromisoformat(raw["available_at"]),
                datetime.fromisoformat(file_state.available_at),
            )
            .astimezone(UTC)
            .isoformat()
        )
    return raw["available_at"]


def _handled(product_id: str, center_id: str, target: date, periods: list[dict]) -> bool:
    return any(
        item["canonical_product_id"] == product_id
        and item["center_id"] == center_id
        and date.fromisoformat(item["valid_from"]) <= target
        and (item["valid_to"] is None or target <= date.fromisoformat(item["valid_to"]))
        for item in periods
    )


def _dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
