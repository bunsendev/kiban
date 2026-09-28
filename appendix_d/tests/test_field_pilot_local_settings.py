"""現場設定の版、時点選択、復帰、変更前境界を確認する。"""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.field_pilot.local_setting_service import LocalSettingService
from forecast_provider.field_pilot.local_setting_store import LocalSettingStore
from forecast_provider.field_pilot.read_model import FieldPilotReadService
from forecast_provider.jobs import SqliteRunStore

NOW = datetime(2026, 9, 28, 1, tzinfo=UTC)
DAY = date(2026, 9, 28)


def _change(service, *, jan="4901234567894", expected=None, now=NOW):
    return service.change(
        change_type="JAN_MAPPING", target="ITEM-1",
        value={"jan": jan, "product_name": "商品A"}, effective_from=DAY,
        actor="WINDOWS:operator", reason_code="CORRECTION", comment="照合済み",
        expected_version=expected, now=now,
    )


def test_jan_change_history_and_rollback_are_append_only(tmp_path):
    store = LocalSettingStore(tmp_path / "Config" / "field-settings.sqlite3")
    backups = []
    service = LocalSettingService(store, "v1", before_change=lambda: backups.append("backup"))
    first = _change(service)
    second = _change(service, jan="4901234567887", expected=first["version"],
                     now=NOW + timedelta(minutes=1))
    assert store.current("JAN_MAPPING", "ITEM-1", business_date=DAY,
                         known_at=NOW + timedelta(seconds=30))["version"] == first["version"]
    assert store.current("JAN_MAPPING", "ITEM-1", business_date=DAY,
                         known_at=NOW + timedelta(minutes=2))["version"] == second["version"]
    restored = service.restore_previous(
        version=first["version"], actor="WINDOWS:operator", expected_version=second["version"],
        comment="前の設定へ戻す", now=NOW + timedelta(minutes=2),
    )
    assert restored["version"] not in {first["version"], second["version"]}
    assert restored["rollback_of"] == first["version"]
    assert restored["old_version"] == second["version"]
    assert store.current("JAN_MAPPING", "ITEM-1", business_date=DAY,
                         known_at=NOW + timedelta(minutes=3))["value"] == first["value"]
    assert len(store.history("JAN_MAPPING", "ITEM-1")) == 3
    assert len(backups) == 3
    assert LocalSettingStore(store.path).history("JAN_MAPPING", "ITEM-1") == store.history(
        "JAN_MAPPING", "ITEM-1",
    )


def test_inventory_time_keeps_day_precision_and_rejects_fictional_exact_time(tmp_path):
    store = LocalSettingStore(tmp_path / "field-settings.sqlite3")
    service = LocalSettingService(store, "v1")
    saved = service.change(
        change_type="INVENTORY_TIME_POLICY", target="WAREHOUSE",
        value={"source": "DAILY_CLOSE", "precision": "BUSINESS_DAY",
               "time_zone": "Asia/Tokyo"},
        effective_from=DAY, actor="WINDOWS:operator",
        reason_code="INITIAL_CONFIRMATION", comment="日付のみ確認済み",
        expected_version=None, now=NOW,
    )
    assert saved["value"]["precision"] == "BUSINESS_DAY"
    with pytest.raises(ValueError, match="EXACT_TIME_SOURCE_REQUIRED"):
        service.change(
            change_type="INVENTORY_TIME_POLICY", target="WAREHOUSE",
            value={"source": "DAILY_CLOSE", "precision": "EXACT_TIME",
                   "time_zone": "Asia/Tokyo"},
            effective_from=DAY, actor="WINDOWS:operator",
            reason_code="CORRECTION", comment="", expected_version=saved["version"], now=NOW,
        )
    assert len(store.history("INVENTORY_TIME_POLICY", "WAREHOUSE")) == 1


def test_rollback_supersedes_future_scheduled_version(tmp_path):
    store = LocalSettingStore(tmp_path / "field-settings.sqlite3")
    service = LocalSettingService(store, "v1")
    first = _change(service)
    future = service.change(
        change_type="JAN_MAPPING", target="ITEM-1",
        value={"jan": "4901234567887", "product_name": "商品A"},
        effective_from=DAY + timedelta(days=2), actor="admin",
        reason_code="BUSINESS_RULE_CHANGE", comment="将来の変更",
        expected_version=first["version"], now=NOW + timedelta(minutes=1),
    )
    assert store.current("JAN_MAPPING", "ITEM-1", business_date=DAY,
                         known_at=NOW + timedelta(minutes=2))["version"] == first["version"]
    restored = service.restore_previous(
        version=first["version"], actor="admin", expected_version=future["version"],
        comment="将来の変更を取り消し", now=NOW + timedelta(minutes=2),
    )
    assert store.current("JAN_MAPPING", "ITEM-1", business_date=DAY + timedelta(days=3),
                         known_at=NOW + timedelta(days=3))["version"] == restored["version"]


def test_invalid_or_stale_change_never_replaces_current_setting(tmp_path):
    store = LocalSettingStore(tmp_path / "field-settings.sqlite3")
    service = LocalSettingService(store, "v1")
    first = _change(service)
    with pytest.raises(ValueError, match="LOCAL_SETTING_VERSION_CONFLICT"):
        _change(service, expected=None, now=NOW + timedelta(minutes=1))
    with pytest.raises(ValueError, match="LOCAL_SETTING_RETROACTIVE_CHANGE"):
        service.change(
            change_type="JAN_MAPPING", target="ITEM-1",
            value={"jan": "4901234567894", "product_name": "商品A"},
            effective_from=DAY - timedelta(days=1), actor="WINDOWS:operator",
            reason_code="CORRECTION", comment="", expected_version=first["version"], now=NOW,
        )
    with pytest.raises(ValueError):
        _change(service, jan="4901234567890", expected=first["version"])
    assert len(store.history("JAN_MAPPING", "ITEM-1")) == 1


def test_change_creates_verified_sqlite_backup_before_write(tmp_path):
    store = LocalSettingStore(tmp_path / "Config" / "field-settings.sqlite3")
    service = LocalSettingService(store, "v1")
    first = _change(service)
    _change(service, expected=first["version"], now=NOW + timedelta(minutes=1))
    backups = sorted((tmp_path / "Backup").glob("settings-*.sqlite3"))
    assert len(backups) == 2
    for backup in backups:
        manifest = json.loads(backup.with_suffix(".json").read_text(encoding="utf-8"))
        assert manifest["sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
        assert LocalSettingStore(backup).targets("JAN_MAPPING") in ([], ["ITEM-1"])


def test_backup_failure_blocks_change(tmp_path):
    store = LocalSettingStore(tmp_path / "field-settings.sqlite3")

    def fail_backup():
        raise OSError("backup unavailable")

    service = LocalSettingService(store, "v1", before_change=fail_backup)
    with pytest.raises(OSError, match="backup unavailable"):
        _change(service)
    assert store.history("JAN_MAPPING", "ITEM-1") == []


def test_setting_api_requires_admin_and_keeps_shadow_boundary(tmp_path):
    service = FieldPilotReadService(None, tmp_path / "Config" / "pilot-settings.json",
                                    learning_admin_token="admin-secret")
    app = create_app(SqliteRunStore(tmp_path / "app.sqlite3"),
                     SqliteCatalogStore(tmp_path / "app.sqlite3"), "api-secret",
                     field_pilot=service)
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/ui/pilot/settings").status_code == 200
    assert client.get("/ui/assets/pilot_settings.js").status_code == 200
    assert client.get("/api/field-pilot/settings").status_code == 403
    payload = {
        "change_type": "JAN_MAPPING", "target": "ITEM-1",
        "value": {"jan": "4901234567894", "product_name": "商品A"},
        "effective_from": datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat(), "actor": "admin",
        "reason_code": "INITIAL_CONFIRMATION", "comment": "原本照合済み",
        "expected_version": None,
    }
    path = "/api/field-pilot/settings/change"
    assert client.post(path, json=payload).status_code == 403
    headers = {"X-Field-Pilot-Admin-Token": "admin-secret"}
    assert client.post(
        path, json=payload, headers={**headers, "Origin": "https://evil"},
    ).status_code == 403
    saved = client.post(path, json=payload, headers=headers)
    assert saved.status_code == 200
    version = saved.json()["version"]
    viewed = client.get("/api/field-pilot/settings?change_type=JAN_MAPPING&target=ITEM-1",
                        headers=headers)
    assert viewed.status_code == 200
    assert viewed.json()["current"]["version"] == version
    assert len(viewed.json()["history"]) == 1
    assert client.post(path, json=payload, headers=headers).status_code == 409
    assert client.post("/api/field-shadow/preview", json={}, headers=headers).status_code == 405
