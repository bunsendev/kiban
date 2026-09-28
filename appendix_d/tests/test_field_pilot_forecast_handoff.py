"""確認済み商品だけを次工程候補とする引継ぎ判定。"""

from datetime import date
from types import SimpleNamespace

from forecast_provider.field_pilot.forecast_handoff import forecast_handoff


class Inventory:
    def __init__(self):
        self.snapshots = [self.snapshot("stock-1", "2026-09-29T07:00:00+09:00")]
        self.decisions = {"stock-1": "APPROVED"}

    @staticmethod
    def snapshot(snapshot_id, snapshot_at):
        return {"snapshot_id": snapshot_id, "job_id": snapshot_id,
                "snapshot_at": snapshot_at, "normalized_unit": "CASE",
                "product_mapping_version": "mapping-1"}

    def list_snapshots(self):
        return self.snapshots

    def get_latest_snapshot_decision(self, snapshot_id):
        value = self.decisions.get(snapshot_id)
        return {"decision": value} if value else None

    def get_job(self, job_id):
        return SimpleNamespace(status="SUCCEEDED", quarantined_row_count=0)

    def get_reconciliation(self, job_id):
        return {"reconciled": True}

    def list_product_mappings(self, mapping_version):
        return [SimpleNamespace(source_product_code="ITEM-1", jan="4901234567894")]

    def list_expiry_buckets_with_location(self, snapshot_id):
        return [{"jan": "4901234567894", "location_type": "WAREHOUSE",
                 "location_code": "EAST", "normalized_unit": "CASE",
                 "issue_codes": []}]


def _review():
    return {"complete": True, "confirmed_items": [{"product_code": "ITEM-1",
             "jan": "4901234567894", "evidence_status": "HISTORY_PRESENT"}]}


def _trial():
    return {"status": "TRIAL_READY", "product_code": "ITEM-1", "unit": "CASE",
            "policy_version": "local-1", "source_fingerprint": "a" * 64,
            "series": [{"warehouse_code": "EAST", "last_observed_day": "2026-09-28",
                        "observed_days_in_window": 28, "used_days_in_window": 28,
                        "historical_replay": False}]}


def test_handoff_candidate_requires_matching_approved_inventory():
    inventory = Inventory()
    result = forecast_handoff(_review(), _trial(), inventory,
                              business_date=date(2026, 9, 29))
    assert result["preparation_candidate_count"] == 1
    assert result["series"][0]["inventory_snapshot_id"] == "stock-1"
    assert result["formal_forecast_ready"] is False
    assert result["formal_next_gate"] == "FORMAL_SHIPMENT_NORMALIZATION_AND_DAILY_BUILD_REQUIRED"

    inventory.snapshots.append(inventory.snapshot("stock-2", "2026-09-29T08:00:00+09:00"))
    blocked = forecast_handoff(_review(), _trial(), inventory,
                               business_date=date(2026, 9, 29))
    assert blocked["preparation_candidate_count"] == 0
    assert "APPROVED_CASE_INVENTORY_MISSING" in blocked["series"][0]["blocking_reasons"]


def test_handoff_keeps_other_series_when_one_is_missing_and_never_converts_units():
    trial = _trial()
    trial["series"].append({"warehouse_code": "WEST", "last_observed_day": "2026-09-15",
                            "observed_days_in_window": 19, "used_days_in_window": 19,
                            "historical_replay": True})
    result = forecast_handoff(_review(), trial, Inventory(),
                              business_date=date(2026, 9, 29))
    assert result["preparation_candidate_count"] == 1
    assert result["series"][1]["blocking_reasons"] == [
        "DAILY_COVERAGE_INCOMPLETE", "SHIPMENT_HISTORY_OLD",
        "APPROVED_CASE_INVENTORY_MISSING",
    ]
    trial["unit"] = "PALLET"
    blocked = forecast_handoff(_review(), trial, Inventory(),
                               business_date=date(2026, 9, 29))
    assert blocked["preparation_candidate_count"] == 0
    assert "SHIPMENT_CASE_UNIT_NOT_CONFIRMED" in blocked["series"][0]["blocking_reasons"]


def test_handoff_rejects_conflict_unreadable_sources_and_future_inventory():
    review = _review()
    review["complete"] = False
    review["confirmed_items"][0]["evidence_status"] = "JAN_CONFLICT"
    inventory = Inventory()
    inventory.snapshots[0]["snapshot_at"] = "2026-09-30T09:00:00+09:00"
    result = forecast_handoff(review, _trial(), inventory,
                              business_date=date(2026, 9, 29))
    assert result["preparation_candidate_count"] == 0
    assert result["series"][0]["blocking_reasons"] == [
        "SOURCE_FILES_UNREADABLE", "JAN_CONFLICT", "APPROVED_CASE_INVENTORY_MISSING",
    ]


def test_latest_inventory_with_expiry_issue_blocks_older_approved_snapshot():
    inventory = Inventory()
    inventory.snapshots.append(inventory.snapshot("stock-2", "2026-09-29T08:00:00+09:00"))
    inventory.decisions["stock-2"] = "APPROVED"
    original = inventory.list_expiry_buckets_with_location

    def buckets(snapshot_id):
        values = original(snapshot_id)
        if snapshot_id == "stock-2":
            values[0]["issue_codes"] = ["EXPIRY_UNKNOWN"]
        return values

    inventory.list_expiry_buckets_with_location = buckets
    result = forecast_handoff(_review(), _trial(), inventory,
                              business_date=date(2026, 9, 29))
    assert result["preparation_candidate_count"] == 0
    assert result["series"][0]["inventory_snapshot_id"] is None
