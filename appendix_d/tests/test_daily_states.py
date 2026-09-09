"""利用可能時刻・休業日・日次状態のPhase 1J単体適合試験。"""

from datetime import UTC, date, datetime
from decimal import Decimal

from daily_support import schedule_payload

from forecast_provider.daily import make_closed_day, make_file_schedule
from forecast_provider.daily.aggregation import aggregate_shipments
from forecast_provider.daily.calendar import known_closed_days
from forecast_provider.daily.completeness import evaluate_completeness
from forecast_provider.daily.contracts import FileCompleteness
from forecast_provider.daily.states import decide_daily_values


def test_rows_and_closures_after_as_of_are_not_used():
    payload = schedule_payload()
    payload["valid_to"] = "2026-01-01"
    payload["files"] = [
        {
            "logical_path": "observed.csv",
            "center_id": "C1",
            "file_type": "SHIPMENT",
            "target_start": "2026-01-01",
            "target_end": "2026-01-01",
            "absence_means_zero": True,
        }
    ]
    source = {
        "logical_path": "observed.csv",
        "status": "SUCCEEDED",
        "source_created_at": "2026-01-03T00:00:00+00:00",
        "rows": [
            {
                "status": "ACCEPTED",
                "shipment_date": "2026-01-01",
                "center_id": "C1",
                "raw_jan": "001",
                "quantity": "2",
                "available_at": "2026-01-03T00:00:00+00:00",
            }
        ],
    }
    cutoff = datetime(2026, 1, 2, tzinfo=UTC)
    completeness = evaluate_completeness(
        "build",
        make_file_schedule(payload),
        [source],
        date(2026, 1, 1),
        date(2026, 1, 1),
        cutoff,
        "OBSERVED",
    )
    aggregates = aggregate_shipments(
        [source],
        [
            {
                "jan": "001",
                "canonical_product_id": "p1",
                "valid_from": "2026-01-01",
                "valid_to": None,
            }
        ],
        date(2026, 1, 1),
        date(2026, 1, 1),
        cutoff,
    )
    closure = make_closed_day(
        "C1",
        "2026-01-01",
        "closure-v1",
        "2026-01-03T00:00:00+00:00",
        "operator@example.test",
        "後日確定",
    )
    assert completeness[0].status == "MISSING"
    assert aggregates == {}
    assert known_closed_days([closure], cutoff.isoformat()) == []
    source["rows"][0]["status"] = "QUARANTINED"
    still_missing = evaluate_completeness(
        "build",
        make_file_schedule(payload),
        [source],
        date(2026, 1, 1),
        date(2026, 1, 1),
        cutoff,
        "OBSERVED",
    )
    assert still_missing[0].status == "MISSING"


def test_closed_day_shipment_is_kept_with_issue():
    target = date(2026, 1, 1)
    completeness = [
        FileCompleteness(
            "build",
            "C1",
            target.isoformat(),
            "COMPLETE",
            1,
            1,
            True,
            "2026-01-02T00:00:00+00:00",
        )
    ]
    closure = make_closed_day(
        "C1",
        target.isoformat(),
        "closure-v1",
        "2025-12-01T00:00:00+00:00",
        "operator@example.test",
        "確認済み",
    )
    values = decide_daily_values(
        "build",
        [{"canonical_product_id": "p1", "center_id": "C1"}],
        target,
        target,
        completeness,
        {
            ("p1", "C1", target): {
                "raw_quantity": Decimal("3"),
                "available_at": "2026-01-02T00:00:00+00:00",
            }
        },
        [
            {
                "canonical_product_id": "p1",
                "center_id": "C1",
                "valid_from": "2026-01-01",
                "valid_to": None,
            }
        ],
        [closure],
        "2026-01-03T00:00:00+00:00",
        "OBSERVED",
    )
    assert values[0].state == "OBSERVED"
    assert values[0].y == Decimal("3")
    assert values[0].issue == "SHIPMENT_ON_CLOSED_DAY"
    incomplete = [
        FileCompleteness(
            "build",
            "C1",
            target.isoformat(),
            "MISSING",
            1,
            0,
            False,
            "2026-01-03T00:00:00+00:00",
            ("missing.csv",),
        )
    ]
    partial = decide_daily_values(
        "build",
        [{"canonical_product_id": "p1", "center_id": "C1"}],
        target,
        target,
        incomplete,
        {
            ("p1", "C1", target): {
                "raw_quantity": Decimal("3"),
                "available_at": "2026-01-02T00:00:00+00:00",
            }
        },
        [
            {
                "canonical_product_id": "p1",
                "center_id": "C1",
                "valid_from": "2026-01-01",
                "valid_to": None,
            }
        ],
        [closure],
        "2026-01-03T00:00:00+00:00",
        "OBSERVED",
    )
    assert partial[0].state == "PARTIAL_OR_INVALID"
    assert partial[0].raw_quantity == Decimal("3")
    assert partial[0].y is None
    assert partial[0].issue == "INCOMPLETE_FILES_WITH_SHIPMENT_ON_CLOSED_DAY"
