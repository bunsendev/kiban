"""Field Pilotの読み取り専用境界と現場画面を人工Pilotで確認する。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.expiry_simulation import ExpirySimulationService
from forecast_provider.field_pilot import FieldPilotReadService
from forecast_provider.field_ui import FieldShadowPreviewService
from forecast_provider.jobs import SqliteRunStore
from tests.test_phase3ta1_pilot_intake import NOW, _jan
from tests.test_phase3ta2_warehouse_projection import _ready


def _client(tmp_path: Path):
    projection, scope, bridge, _inventory, _snapshot = _ready(tmp_path)
    config = tmp_path / "pilot-settings.json"
    config.write_text(json.dumps({
        "environment": "FIELD_PILOT", "mode": "SHADOW", "read_only": True,
        "pilot_scope_version": scope.version.pilot_scope_version,
        "identity_bridge_version": bridge.version.bridge_version,
        "forecast_run_id": "run-pilot", "minimum_remaining_days": 0,
        "attention_days": 7, "policy_confirmed_by": "reviewer",
        "policy_reason": "人工Pilotの確認", "policy_confirmed_at": NOW.isoformat(),
        "product_labels": {_jan(0): "商品A"},
        "warehouse_labels": {"warehouse-east": "東倉庫"},
    }, ensure_ascii=False), encoding="utf-8")
    shadow = FieldShadowPreviewService(ExpirySimulationService(projection))
    pilot = FieldPilotReadService(shadow, config)
    path = tmp_path / "pilot.sqlite3"
    app = create_app(
        SqliteRunStore(path), SqliteCatalogStore(path), "admin-secret",
        field_shadow=shadow, field_pilot=pilot,
    )
    return TestClient(app, base_url="http://127.0.0.1"), config


def test_field_pilot_reads_approved_shadow_and_hides_other_operations(tmp_path):
    client, _config = _client(tmp_path)
    response = client.get("/api/field-pilot/view")
    assert response.status_code == 200
    view = response.json()
    assert view["status"] == "READY"
    assert view["mode"] == "SHADOW"
    assert view["read_only"] is True
    assert view["summary"]["item_count"] == 10
    assert view["summary"]["shortage_count"] == 10
    first = next(row for row in view["rows"] if row["jan"] == _jan(0))
    assert first["product"] == "商品A"
    assert first["warehouse"] == "東倉庫"
    assert first["current_warehouse_cases"] == "5"
    assert len(first["days"]) == 14
    assert first["expiry_buckets"][0]["opening_cases"] == "5"
    assert "system_reference_quantity" not in first
    assert client.post("/api/field-shadow/preview", json={}).status_code == 405
    assert client.get("/ui/easy").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/ui/pilot").status_code == 200
    assert "試験運用中" in client.get("/ui/pilot").text
    assert client.get("/ui/assets/pilot.js").status_code == 200
    assert client.get("/ui/assets/easy.html").status_code == 404
    assert client.get("/api/field-pilot/view", headers={"Host": "other.example"}).status_code == 403


def test_field_pilot_missing_or_invalid_config_has_safe_message(tmp_path):
    client, config = _client(tmp_path)
    config.unlink()
    missing = client.get("/api/field-pilot/view").json()
    assert missing["status"] == "SETUP_REQUIRED"
    assert "admin" not in missing
    config.write_text('{"mode":"OPERATIONAL"}', encoding="utf-8")
    invalid = client.get("/api/field-pilot/view").json()
    assert invalid["status"] == "SETUP_REQUIRED"


def test_field_pilot_forecast_not_ready_does_not_show_traceback(tmp_path):
    client, config = _client(tmp_path)
    settings = json.loads(config.read_text(encoding="utf-8"))
    settings["forecast_run_id"] = "missing-run"
    config.write_text(json.dumps(settings), encoding="utf-8")
    response = client.get("/api/field-pilot/view")
    assert response.status_code == 200
    assert response.json()["status"] == "DATA_NOT_READY"
    assert "Traceback" not in response.text
