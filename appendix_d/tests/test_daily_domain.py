"""予定ファイル定義と完全性のPhase 1J単体適合試験。"""

from datetime import UTC, date, datetime

import pytest
from daily_support import schedule_payload

from forecast_provider.daily import make_file_schedule
from forecast_provider.daily.completeness import evaluate_completeness


def test_file_schedule_is_content_addressed_and_rejects_ambiguous_ranges():
    first = make_file_schedule(schedule_payload())
    reversed_files = schedule_payload()
    reversed_files["files"].reverse()
    assert make_file_schedule(reversed_files) == first
    invalid = schedule_payload()
    invalid["files"][0]["target_start"] = "2025-12-31"
    with pytest.raises(ValueError, match="有効期間内"):
        make_file_schedule(invalid)


def test_zero_expected_files_are_missing_and_partial_files_are_not_complete():
    payload = schedule_payload()
    payload["files"] = [
        {
            "logical_path": path,
            "center_id": "C1",
            "file_type": "SHIPMENT",
            "target_start": "2026-01-01",
            "target_end": "2026-01-01",
            "absence_means_zero": True,
        }
        for path in ("part-a.csv", "part-b.csv")
    ]
    source = {
        "logical_path": "part-a.csv",
        "status": "SUCCEEDED",
        "rows": [{"status": "ACCEPTED", "shipment_date": "2026-01-01", "center_id": "C1"}],
    }
    values = evaluate_completeness(
        "build",
        make_file_schedule(payload),
        [source],
        date(2026, 1, 1),
        date(2026, 1, 2),
        datetime(2026, 1, 3, tzinfo=UTC),
        "ASSUMED",
    )
    assert values[0].status == "PARTIAL_OR_INVALID"
    assert values[0].missing_paths == ("part-b.csv",)
    assert values[1].status == "MISSING"
    assert values[1].expected_count == 0
