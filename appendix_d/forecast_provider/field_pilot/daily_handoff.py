"""凍結した現場出荷履歴と正式日次build入力を日別に照合する。"""

from datetime import date, datetime
from decimal import Decimal

from ..daily.aggregation import aggregate_shipments
from ..daily.calendar import known_closed_days
from ..daily.completeness import evaluate_completeness
from ..daily.states import decide_daily_values


def validate_daily_handoff(history: dict, job, daily) -> dict:
    """正式入力の値・状態が凍結履歴と完全一致する場合だけ登録可能とする。"""
    if history["unit"] != "CASE":
        raise ValueError("DAILY_HANDOFF_UNIT_MISMATCH")
    definition = job.definition
    rows = history["daily_rows"]
    first, last = rows[0]["date"], rows[-1]["date"]
    if (definition["train_start"] != first or definition["test_end"] != last
            or len(definition["selected_series"]) != 1
            or definition["selected_series"][0]["center_id"] != history["warehouse_code"]):
        raise ValueError("DAILY_HANDOFF_SCOPE_MISMATCH")
    selected = definition["selected_series"][0]
    product_id = selected["canonical_product_id"]
    mappings = daily.list_jan_mappings(definition["mapping_version"])
    for row in rows:
        target = row["date"]
        matches = [item for item in mappings
                   if item["jan"] == history["jan"]
                   and item["valid_from"] <= target
                   and (item["valid_to"] is None or target <= item["valid_to"])]
        if len(matches) != 1 or matches[0]["canonical_product_id"] != product_id:
            raise ValueError("DAILY_HANDOFF_IDENTITY_MISMATCH")
    schedule = daily.get_schedule(definition["schedule_id"])
    sources = daily.source_inputs(job)  # 採用済み原本・成功済み正規化・予定との整合を検査
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    as_of = datetime.fromisoformat(definition["as_of"])
    completeness = evaluate_completeness(
        job.build_id, schedule, sources, start, end, as_of,
        definition["availability_mode"],
    )
    aggregates = aggregate_shipments(sources, mappings, start, end, as_of)
    closed = (known_closed_days(
        daily.list_closed_days(definition["closure_version"]), definition["as_of"],
    ) if definition["closure_version"] is not None else [])
    values = decide_daily_values(
        job.build_id, definition["selected_series"], start, end, completeness,
        aggregates, daily.list_handling_periods(definition["period_version"]),
        closed, definition["as_of"], definition["availability_mode"],
    )
    expected_states = {
        "OBSERVED": "OBSERVED",
        "ZERO_BY_CONFIRMED_POLICY": "CONFIRMED_ZERO",
        "MISSING": "MISSING",
    }
    if len(values) != len(rows):
        raise ValueError("DAILY_HANDOFF_COVERAGE_MISMATCH")
    for frozen, formal in zip(rows, values, strict=True):
        expected = expected_states.get(frozen["state"])
        if (formal.ds != frozen["date"] or formal.state != expected
                or (frozen["quantity_case"] is None) != (formal.y is None)
                or (frozen["quantity_case"] is not None
                    and Decimal(frozen["quantity_case"]) != formal.y)):
            raise ValueError(f"DAILY_HANDOFF_VALUE_MISMATCH:{frozen['date']}")
    return {"history_day_count": len(rows), "build_id": job.build_id,
            "missing_day_count": sum(row["state"] == "MISSING" for row in rows),
            "daily_build_ready": True, "forecast_ready": False}
