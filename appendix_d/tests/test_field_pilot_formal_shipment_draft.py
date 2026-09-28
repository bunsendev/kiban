"""現場の確認結果を、出荷日次入力候補として凍結する境界。"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.field_pilot.formal_shipment_draft import (
    FormalShipmentDraftStore,
    make_formal_shipment_draft,
)
from forecast_provider.field_pilot.formal_shipment_history import (
    FormalShipmentHistoryStore,
    materialize_history,
)
from forecast_provider.field_pilot.read_model import FieldPilotReadService
from forecast_provider.jobs import SqliteRunStore
from tests.test_field_pilot_forecast_handoff import Inventory
from tests.test_field_pilot_shipment_trial import JAN, _setting, _source


def _evidence():
    latest = date(2026, 9, 28)
    history = [
        {"date": (latest - timedelta(days=27 - index)).isoformat(),
         "quantity": "0" if index == 5 else "2.50",
         "state": "ZERO_BY_CONFIRMED_POLICY" if index == 5 else "OBSERVED"}
        for index in range(28)
    ]
    trial = {
        "status": "TRIAL_READY", "unit": "CASE", "product_code": "A1",
        "source_fingerprint": "a" * 64, "policy_version": "local-1",
        "missing_day": "ZERO_WHEN_DAILY_FILE_PRESENT",
        "series": [{"warehouse_code": "EAST", "last_observed_day": latest.isoformat(),
                    "history": history}],
    }
    handoff = {
        "product_code": "A1", "jan": "4901234567894",
        "source_fingerprint": "a" * 64, "trial_policy_version": "local-1",
        "business_date": "2026-09-29",
        "series": [{"warehouse_code": "EAST", "preparation_candidate": True,
                    "inventory_snapshot_id": "stock-1"}],
    }
    return trial, handoff


def _approve(trial, handoff, **overrides):
    arguments = {
        "warehouse_code": "EAST", "expected_source_fingerprint": "a" * 64,
        "expected_policy_version": "local-1",
        "expected_inventory_snapshot_id": "stock-1",
        "actor": "manager", "reason": "原本で箱単位とゼロ日を確認",
        "approved_at": datetime(2026, 9, 29, tzinfo=UTC),
    }
    arguments.update(overrides)
    return make_formal_shipment_draft(trial, handoff, **arguments)


def test_draft_freezes_exact_daily_rows_and_is_idempotent(tmp_path):
    trial, handoff = _evidence()
    draft = _approve(trial, handoff)
    assert len(draft["content"]["daily_rows"]) == 28
    assert draft["content"]["daily_rows"][5] == {
        "date": "2026-09-06", "quantity_case": "0", "state": "ZERO_BY_CONFIRMED_POLICY",
    }
    assert draft["content"]["unit"] == "CASE"
    assert draft["daily_build_ready"] is False
    store = FormalShipmentDraftStore(tmp_path / "drafts.sqlite3")
    assert store.put(draft) == store.put(_approve(trial, handoff, actor="second"))
    trial["series"][0]["history"][0]["quantity"] = "3"
    assert _approve(trial, handoff)["draft_id"] != draft["draft_id"]


def test_full_history_preserves_missing_and_confirmed_zero(tmp_path):
    trial, handoff = _evidence()
    draft = _approve(trial, handoff)
    trial["series"][0]["full_history"] = [
        {"date": "2026-08-30", "quantity": "3", "state": "OBSERVED"},
        {"date": "2026-08-31", "quantity": None, "state": "MISSING"},
    ] + trial["series"][0]["history"]
    result = materialize_history(draft, trial, handoff)
    assert result["day_count"] == 30
    assert result["missing_day_count"] == 1
    assert result["zero_by_policy_day_count"] == 1
    assert result["content"]["daily_rows"][1]["quantity_case"] is None
    assert result["daily_build_ready"] is False
    assert "FULL_HISTORY_MISSING_DAYS" in result["blocking_reasons"]
    store = FormalShipmentHistoryStore(tmp_path / "drafts.sqlite3")
    assert store.put(result) == store.put(result)
    assert store.get(result["history_id"]) == result["content"]


def test_full_history_rejects_changed_source_or_recent_rows():
    trial, handoff = _evidence()
    draft = _approve(trial, handoff)
    trial["series"][0]["full_history"] = list(trial["series"][0]["history"])
    trial["source_fingerprint"] = "b" * 64
    with pytest.raises(ValueError, match="FORMAL_HISTORY_EVIDENCE_CHANGED"):
        materialize_history(draft, trial, handoff)
    trial["source_fingerprint"] = "a" * 64
    trial["series"][0]["full_history"][0] = {
        "date": trial["series"][0]["full_history"][0]["date"],
        "quantity": "9", "state": "OBSERVED",
    }
    with pytest.raises(ValueError, match="FORMAL_HISTORY_DRAFT_MISMATCH"):
        materialize_history(draft, trial, handoff)


@pytest.mark.parametrize("change", [
    "fingerprint", "policy", "inventory", "unit", "coverage", "missing",
    "stale", "zero", "zero_policy", "candidate",
])
def test_draft_rejects_stale_or_ambiguous_evidence(change):
    trial, handoff = _evidence()
    kwargs = {}
    if change == "fingerprint":
        kwargs["expected_source_fingerprint"] = "b" * 64
    elif change == "policy":
        kwargs["expected_policy_version"] = "local-old"
    elif change == "inventory":
        kwargs["expected_inventory_snapshot_id"] = "stock-old"
    elif change == "unit":
        trial["unit"] = "PALLET"
    elif change == "coverage":
        trial["series"][0]["history"].pop()
    elif change == "missing":
        trial["series"][0]["history"][0]["quantity"] = None
    elif change == "stale":
        trial["series"][0]["last_observed_day"] = "2026-09-20"
    elif change == "zero":
        trial["series"][0]["history"][5]["quantity"] = "2"
    elif change == "zero_policy":
        trial["missing_day"] = "OBSERVED_ONLY"
    elif change == "candidate":
        handoff["series"][0]["preparation_candidate"] = False
    with pytest.raises(ValueError, match="FORMAL_SHIPMENT_"):
        _approve(trial, handoff, **kwargs)


def test_admin_can_freeze_ready_series_but_stale_source_is_rejected(tmp_path):
    inbox = _source(tmp_path)
    inventory = Inventory()
    inventory.list_product_mappings = lambda version: [
        SimpleNamespace(source_product_code="A1", jan=JAN),
    ]
    service = FieldPilotReadService(
        None, tmp_path / "config.json", inbox_root=inbox,
        inventory_store=inventory, learning_admin_token="secret",
    )
    _setting(service.local_settings.store, "JAN_MAPPING",
             {"jan": JAN, "product_name": "商品A"})
    _setting(service.local_settings.store, "SHIPMENT_TRIAL_POLICY", {
        "unit": "CASE", "missing_day": "OBSERVED_ONLY",
    })
    app = create_app(SqliteRunStore(tmp_path / "api.sqlite3"),
                     SqliteCatalogStore(tmp_path / "api.sqlite3"), "api-secret",
                     field_pilot=service)
    headers = {"X-Field-Pilot-Admin-Token": "secret"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        preparation = client.post("/api/field-pilot/admin/forecast-preparation",
                                  json={"product_code": "A1"}, headers=headers).json()
        assert preparation["preparation_candidate_count"] == 1
        body = {
            "product_code": "A1", "warehouse_code": "EAST",
            "source_fingerprint": preparation["source_fingerprint"],
            "policy_version": preparation["trial_policy_version"],
            "inventory_snapshot_id": preparation["series"][0]["inventory_snapshot_id"],
            "actor": "manager", "reason": "箱単位と日別記録を確認",
        }
        url = "/api/field-pilot/admin/formal-shipment-drafts"
        saved = client.post(url, json=body, headers=headers)
        assert saved.status_code == 200
        assert saved.json()["content"]["daily_rows"][0]["quantity_case"] == "2"
        again = client.post(url, json=body, headers=headers)
        assert again.json()["draft_id"] == saved.json()["draft_id"]
        history_url = "/api/field-pilot/admin/formal-shipment-history"
        history_request = {"draft_id": saved.json()["draft_id"]}
        assert client.post(history_url, json=history_request).status_code == 403
        history_response = client.post(history_url, json=history_request, headers=headers)
        assert history_response.status_code == 200
        assert history_response.json()["day_count"] == 28
        assert history_response.json()["daily_build_ready"] is False
        source = inbox / "Archive" / "ab" / "abcdef" / "shipment.csv"
        source.write_bytes(source.read_bytes() + b"\n")
        assert client.post(url, json=body, headers=headers).status_code == 409
        assert client.post(history_url, json=history_request,
                           headers=headers).status_code == 409
