"""承認済みPilotのProjection/FEFOをShadow参考値として表示する境界。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.expiry_simulation import ExpirySimulationService
from forecast_provider.field_ui import FieldShadowPreviewService
from forecast_provider.jobs import SqliteRunStore
from tests.test_phase3ta1_pilot_intake import NOW, _jan
from tests.test_phase3ta2_warehouse_projection import _ready


def _setup_preview(tmp_path):
    projection_service, scope, bridge, _inventory, snapshot_id = _ready(tmp_path)
    path = tmp_path / "pilot.sqlite3"
    api = TestClient(create_app(
        SqliteRunStore(path), SqliteCatalogStore(path), "token",
        field_shadow=FieldShadowPreviewService(ExpirySimulationService(projection_service)),
    ))
    body = {
        "calculation_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        "pilot_scope_version": scope.version.pilot_scope_version,
        "identity_bridge_version": bridge.version.bridge_version,
        "forecast_run_id": "run-pilot",
        "minimum_remaining_days": 0,
        "attention_days": 7,
        "policy_confirmed_by": "reviewer",
        "policy_reason": "人工PilotのShadow条件確認",
        "policy_confirmed_at": NOW.isoformat(),
    }
    return api, body, snapshot_id


def test_preview_is_read_only_and_omits_unconfirmed_replenishment(tmp_path):
    api, body, snapshot_id = _setup_preview(tmp_path)
    response = api.post(
        "/api/field-shadow/preview", json=body,
        headers={"Authorization": "Bearer token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "SHADOW"
    assert data["inventory_snapshot_id"] == snapshot_id
    assert len(data["rows"]) == 10
    item = next(row for row in data["rows"] if row["jan"] == _jan(0))
    assert item["current_warehouse_cases"] == "5"
    assert item["forecast_7_days_cases"] == "7"
    assert item["forecast_14_days_cases"] == "14"
    assert item["first_gross_shortage_date"]
    assert item["fefo_unmet_14_days_cases"] == "9"
    assert len(item["days"]) == 14
    assert item["system_reference_quantity"] is None
    assert item["reference_case_id"] is None
    assert data["reference_quantity_status"] == "NOT_CALCULATED_POLICY_UNCONFIRMED"
    assert api.post("/api/field-shadow/preview", json=body).status_code == 401


def test_preview_rejects_unconfirmed_policy_and_missing_prediction(tmp_path):
    api, body, _snapshot_id = _setup_preview(tmp_path)
    future_policy = {
        **body,
        "policy_confirmed_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    response = api.post(
        "/api/field-shadow/preview", json=future_policy,
        headers={"Authorization": "Bearer token"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "EXPIRY_POLICY_NOT_KNOWN_AS_OF"
    missing = {**body, "forecast_run_id": "not-found"}
    response = api.post(
        "/api/field-shadow/preview", json=missing,
        headers={"Authorization": "Bearer token"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "FORECAST_RUN_NOT_AVAILABLE_AS_OF"


def test_shadow_page_has_persistent_non_operational_warning(tmp_path):
    api, _body, _snapshot_id = _setup_preview(tmp_path)
    page = api.get("/ui/shadow")
    assert page.status_code == 200
    assert "SHADOW・参考値・検証中" in page.text
    assert "出荷指示ではありません" in page.text
    assert "参考補充量と担当者判断は表示・登録しません" in page.text
    assert page.headers["cache-control"] == "no-store"
