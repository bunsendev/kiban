"""改善台帳・鮮度Gate・後日実績照合の境界を確認する。"""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from forecast_provider.field_pilot.freshness import FreshnessPolicy
from forecast_provider.field_pilot.improvement_events import ImprovementEventLedger
from forecast_provider.field_pilot.improvement_report import weekly_field_report
from forecast_provider.field_pilot.inbox_ledger import InboxLedger
from forecast_provider.field_pilot.inbox_processor import InboxProcessor
from forecast_provider.field_pilot.read_model import FieldPilotReadService
from tests.test_field_pilot_unified_inbox import _policy, _stage


def test_improvement_ledger_rejects_raw_fields_and_keeps_unknown_kpis_null(tmp_path):
    ledger = ImprovementEventLedger(tmp_path / "events.sqlite3")
    now = datetime(2026, 9, 28, 1, tzinfo=UTC)
    ledger.append("VIEW_BLOCKED", outcome="BLOCKED", business_date=date(2026, 9, 28),
                  occurred_at=now, error_code="SNAPSHOT_TOO_OLD")
    with pytest.raises(ValueError):
        ledger.append("VIEW_READY", outcome="OK", metrics={"raw_row": 1})
    with pytest.raises(ValueError):
        ledger.append("VIEW_READY", outcome="OK", location_id="name with spaces")
    report = ledger.weekly_summary(date(2026, 9, 28))
    assert report["event_counts"][0]["n"] == 1
    assert report["business_kpis"]["stockout_cases"] is None
    assert ledger.delete_before(now + timedelta(seconds=1)) == 1
    assert ledger.weekly_summary(date(2026, 9, 28))["event_counts"] == []


def test_freshness_policy_blocks_missing_old_wrong_day_and_future():
    with pytest.raises(ValueError):
        FreshnessPolicy.from_settings({})
    policy = FreshnessPolicy.from_settings({"freshness_policy": {
        "version": "fresh-v1", "max_snapshot_age_hours": 6,
    }})
    now = datetime(2026, 9, 28, 6, tzinfo=UTC)
    assert policy.check("2026-09-28T03:00:00+00:00", now) is None
    assert policy.check("2026-09-27T23:00:00+00:00", now) == "SNAPSHOT_TOO_OLD"
    assert policy.check("2026-09-27T05:00:00+00:00", now) == "SNAPSHOT_BUSINESS_DATE_MISMATCH"
    assert policy.check("2026-09-28T07:00:00+00:00", now) == "SNAPSHOT_IN_FUTURE"


def test_weekly_report_joins_case_decision_actual_and_suppresses_small_gap():
    day = date(2026, 9, 28)
    cases = [SimpleNamespace(case_id=f"c{i}", jan="4901234567894",
                             warehouse_id="W1", business_date=day-timedelta(days=i),
                             system_reference_quantity=Decimal("10"),
                             system_forecast_quantity=Decimal("8")) for i in range(3)]
    decisions = {
        "c0": [SimpleNamespace(operator_quantity=Decimal("15"))],
        "c1": [SimpleNamespace(operator_quantity=Decimal("16"))],
        "c2": [SimpleNamespace(operator_quantity=Decimal("11"))],
    }
    actuals = {"c0": [SimpleNamespace(stockout_quantity=Decimal("2"),
                                       actual_demand_quantity=Decimal("12"),
                                       actual_shipped_quantity=Decimal("14"),
                                       expired_quantity=None,
                                       interwarehouse_transfer_quantity=None)]}

    class Store:
        def list_reference_cases(self, *, limit):
            return cases

        def list_operator_decisions(self, case_id):
            return decisions[case_id]

        def list_actual_outcomes(self, case_id):
            return actuals.get(case_id, [])

    result = weekly_field_report(Store(), day, minimum_gap_cases=Decimal("2"),
                                 repeat_days=3, threshold_version="gap-v1")
    assert result["candidates"][0]["state"] == "REPEATED"
    assert len(result["candidates"][0]["entries"]) == 2
    assert result["business_kpis"]["stockout_cases"] == "2"
    assert result["business_kpis"]["expired_cases"] is None
    comparison = result["candidates"][0]["entries"][0]["comparisons"]
    assert comparison["forecast_vs_actual_demand_cases"] == "4"


def test_pilot_view_blocks_stale_snapshot_even_when_inbox_is_ready(tmp_path):
    now = datetime.now(UTC)

    class Shadow:
        snapshot_at = (now - timedelta(days=1)).isoformat()

        def preview(self, **_kwargs):
            return {"rows": [], "snapshot_at": self.snapshot_at,
                    "calculation_at": now.isoformat(), "forecast_run_id": "run-1",
                    "inventory_snapshot_id": "snapshot-1", "pilot_scope_version": "scope-1",
                    "identity_bridge_version": "bridge-1", "policy_version": "expiry-1"}

    config = tmp_path / "pilot-settings.json"
    settings = {
        "environment": "FIELD_PILOT", "mode": "SHADOW", "read_only": True,
        "pilot_scope_version": "scope-1", "identity_bridge_version": "bridge-1",
        "forecast_run_id": "run-1", "policy_confirmed_by": "reviewer",
        "policy_reason": "reviewed", "policy_confirmed_at": now.isoformat(),
        "minimum_remaining_days": 0, "attention_days": 7,
    }
    config.write_text(json.dumps(settings), encoding="utf-8")
    shadow = Shadow()
    service = FieldPilotReadService(shadow, config, tmp_path / "policy.json", tmp_path)
    service.inbox_view = lambda: {"status": "READY"}
    assert service.view()["status"] == "SETUP_REQUIRED"
    settings["freshness_policy"] = {"version": "fresh-v1", "max_snapshot_age_hours": 24}
    config.write_text(json.dumps(settings), encoding="utf-8")
    assert service.view()["status"] == "DATA_NOT_READY"
    shadow.snapshot_at = now.isoformat()
    assert service.view()["status"] == "READY"
    counts = service.improvement_events.weekly_summary(
        now.astimezone(ZoneInfo("Asia/Tokyo")).date()
    )["event_counts"]
    assert sum(item["n"] for item in counts) == 3


def test_inbox_scan_records_metadata_event_without_raw_rows(tmp_path):
    policy, day = _policy(tmp_path)
    root = tmp_path / "Inbox"
    root.mkdir()
    content = f"day,warehouse,cases\n{day},EAST,4\n".encode()
    _stage(root, "source.csv", content)
    events = ImprovementEventLedger(root / "improvement-events.sqlite3")
    inbox_ledger = InboxLedger(root / "inbox.sqlite3")
    assert InboxProcessor(root, policy, inbox_ledger,
                          improvement_events=events).scan() == 1
    required = inbox_ledger.summary(policy, day)["required"][0]
    assert required["freshness"] == "REVIEW_REQUIRED"
    report = events.weekly_summary(date.fromisoformat(day))
    assert report["event_counts"][0]["event_type"] == "INBOX_CLASSIFIED"
    assert content not in events.path.read_bytes()
    assert b"source.csv" not in events.path.read_bytes()
