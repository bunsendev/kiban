"""凍結履歴を正式日次入力と照合する境界の試験。"""

import hashlib
import json
import sqlite3
from copy import deepcopy

import pytest

from forecast_provider.daily import make_daily_build, make_file_schedule
from forecast_provider.field_pilot.daily_handoff import validate_daily_handoff
from forecast_provider.field_pilot.formal_shipment_history import FormalShipmentHistoryStore
from forecast_provider.field_pilot.read_model import FieldPilotReadService


class DailyFixture:
    def __init__(self):
        self.jobs = []
        self.schedule = make_file_schedule({
            "schedule_version": "v1", "valid_from": "2026-09-01", "valid_to": "2026-09-03",
            "files": [
                {"logical_path": f"shipment-{day}.csv", "center_id": "EAST",
                 "file_type": "SHIPMENT", "target_start": f"2026-09-{day:02d}",
                 "target_end": f"2026-09-{day:02d}", "absence_means_zero": True}
                for day in (1, 2, 3)
            ],
        })
        self.sources = [
            {"logical_path": f"shipment-{day}.csv", "status": "SUCCEEDED",
             "source_created_at": "2026-09-04T00:00:00+00:00",
             "rows": rows}
            for day, rows in ((1, [{"status": "ACCEPTED", "shipment_date": "2026-09-01",
                                     "center_id": "EAST", "raw_jan": "4900000000001",
                                     "quantity": "2",
                                     "available_at": "2026-09-04T00:00:00+00:00"}]),
                              (2, []))
        ]

    def get_schedule(self, _):
        return self.schedule

    def source_inputs(self, _):
        return self.sources

    def list_jan_mappings(self, _):
        return [{"jan": "4900000000001", "canonical_product_id": "product-1",
                 "valid_from": "2026-01-01", "valid_to": None}]

    def list_handling_periods(self, _):
        return [{"canonical_product_id": "product-1", "center_id": "EAST",
                 "valid_from": "2026-01-01", "valid_to": None}]

    def put_job(self, job):
        self.jobs.append(job)


def _job(store):
    return make_daily_build({
        "schedule_id": store.schedule.schedule_id,
        "normalization_ids": ["normal-1", "normal-2"], "mapping_version": "map-1",
        "period_version": "period-1", "closure_version": None,
        "as_of": "2026-09-05T00:00:00+00:00", "selection_version": "selection-1",
        "selected_series": [{"canonical_product_id": "product-1", "center_id": "EAST"}],
        "train_start": "2026-09-01", "train_end": "2026-09-02",
        "test_start": "2026-09-03", "test_end": "2026-09-03",
        "origin_interval_days": 1, "max_horizon": 1, "primary_horizon_max": 1,
        "report_horizons": [1], "availability_mode": "OBSERVED",
    })


def _history():
    return {"jan": "4900000000001", "warehouse_code": "EAST", "unit": "CASE",
            "daily_rows": [
        {"date": "2026-09-01", "quantity_case": "2", "state": "OBSERVED"},
        {"date": "2026-09-02", "quantity_case": "0",
         "state": "ZERO_BY_CONFIRMED_POLICY"},
        {"date": "2026-09-03", "quantity_case": None, "state": "MISSING"},
    ]}


def test_handoff_accepts_only_matching_formal_states_and_quantities():
    daily = DailyFixture()
    job = _job(daily)
    assert validate_daily_handoff(_history(), job, daily) == {
        "history_day_count": 3, "build_id": job.build_id,
        "missing_day_count": 1, "daily_build_ready": True, "forecast_ready": False,
    }
    changed = deepcopy(_history())
    changed["daily_rows"][1]["quantity_case"] = "1"
    with pytest.raises(ValueError, match="DAILY_HANDOFF_VALUE_MISMATCH"):
        validate_daily_handoff(changed, job, daily)
    changed = deepcopy(_history())
    changed["daily_rows"][2]["state"] = "ZERO_BY_CONFIRMED_POLICY"
    changed["daily_rows"][2]["quantity_case"] = "0"
    with pytest.raises(ValueError, match="DAILY_HANDOFF_VALUE_MISMATCH"):
        validate_daily_handoff(changed, job, daily)


def test_handoff_rejects_wrong_identity_and_unproven_zero():
    daily = DailyFixture()
    job = _job(daily)
    changed = deepcopy(_history())
    changed["jan"] = "4900000000002"
    with pytest.raises(ValueError, match="DAILY_HANDOFF_IDENTITY_MISMATCH"):
        validate_daily_handoff(changed, job, daily)
    daily.schedule = make_file_schedule({
        **daily.schedule.definition,
        "files": [{**item, "absence_means_zero": False}
                  for item in daily.schedule.definition["files"]],
    })
    with pytest.raises(ValueError, match="DAILY_HANDOFF_VALUE_MISMATCH"):
        validate_daily_handoff(_history(), job, daily)


def test_history_store_rejects_tampered_local_content(tmp_path):
    content = {"draft_id": "draft-1", **_history()}
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    history_id = "shipment-history-" + hashlib.sha256(canonical.encode()).hexdigest()
    store = FormalShipmentHistoryStore(tmp_path / "history.sqlite3")
    store.put({"history_id": history_id, "content": content})
    assert store.get(history_id) == content
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE formal_shipment_histories SET content_json=? WHERE history_id=?",
                   (json.dumps({**content, "unit": "PALLET"}), history_id))
    with pytest.raises(ValueError, match="FORMAL_HISTORY_INTEGRITY_INVALID"):
        store.get(history_id)


def test_service_does_not_enqueue_mismatched_history(tmp_path):
    daily = DailyFixture()
    content = {"draft_id": "draft-1", **_history()}
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    history_id = "shipment-history-" + hashlib.sha256(canonical.encode()).hexdigest()
    store = FormalShipmentHistoryStore(tmp_path / "formal-shipment-drafts.sqlite3")
    store.put({"history_id": history_id, "content": content})
    service = FieldPilotReadService(None, tmp_path / "config.json")
    job = _job(daily)
    changed = deepcopy(job.definition)
    changed["selected_series"][0]["center_id"] = "WEST"
    with pytest.raises(ValueError, match="DAILY_HANDOFF_SCOPE_MISMATCH"):
        service.create_daily_handoff(history_id, changed, daily)
    assert daily.jobs == []
    accepted = service.create_daily_handoff(history_id, job.definition, daily)
    assert accepted["build_id"] == job.build_id
    assert len(daily.jobs) == 1
