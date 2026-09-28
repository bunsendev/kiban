"""Field Pilot管理画面からの更新確認は認証され、適用を行わない。"""

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.field_pilot import FieldPilotReadService
from forecast_provider.jobs import SqliteRunStore


def test_admin_update_check_requires_token_and_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("KIBAN_FIELD_PILOT_VERSION", "0.1.0-field-pilot.3")
    config = tmp_path / "Config" / "pilot-settings.json"
    config.parent.mkdir()
    service = FieldPilotReadService(
        None, config, learning_admin_token="local-admin-secret",
        local_settings_dir=tmp_path / "LocalSettings",
    )
    app = create_app(
        SqliteRunStore(tmp_path / "api.sqlite3"),
        SqliteCatalogStore(tmp_path / "api.sqlite3"),
        "api-secret", field_pilot=service,
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    status_url = "/api/field-pilot/admin/update"
    check_url = f"{status_url}/check"
    headers = {"X-Field-Pilot-Admin-Token": "local-admin-secret"}

    assert client.get(status_url).status_code == 403
    assert client.post(check_url, json={}).status_code == 403
    assert client.get(status_url, headers=headers).json() == {
        "current_version": "0.1.0-field-pilot.3",
        "channel": "pilot", "public_key_configured": False, "last_check": None,
    }

    class UnusedProvider:
        def check(self, **_):
            raise AssertionError("署名公開鍵なしで通信してはいけない")

    service.update_service.provider = UnusedProvider()
    result = client.post(check_url, json={}, headers=headers)
    assert result.status_code == 200
    assert result.json()["last_check"]["status"] == "UNCONFIGURED"
    assert result.json()["last_check"]["trigger"] == "MANUAL"
    cross_origin = client.post(
        check_url, json={}, headers={**headers, "Origin": "https://evil.test"},
    )
    assert cross_origin.status_code == 403
    assert client.post(f"{status_url}/apply", json={}, headers=headers).status_code == 405
