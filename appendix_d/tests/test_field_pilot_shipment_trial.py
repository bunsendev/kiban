"""確認済み商品だけ、原本単位を保持して参考試算する。"""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.field_pilot.local_setting_store import LocalSettingStore
from forecast_provider.field_pilot.read_model import FieldPilotReadService
from forecast_provider.field_pilot.shipment_trial import trial_forecast
from forecast_provider.jobs import SqliteRunStore

JAN = "4901234567894"


def _source(tmp_path, *, missing_product_day: int | None = None,
            missing_file_day: int | None = None):
    archive = tmp_path / "Inbox" / "Archive" / "ab" / "abcdef"
    archive.mkdir(parents=True)
    (archive / "stock.csv").write_bytes((
        "商品コード,商品名,明細倉庫コード,明細バラ数\n"
        "A1,商品A,EAST,4\nB2,商品B,EAST,5\n"
    ).encode("cp932"))
    rows = ["出荷日,商品コード,商品名,JAN,数量,倉庫コード"]
    for offset in range(28):
        day = date(2026, 9, 1) + timedelta(days=offset)
        if offset == missing_file_day:
            continue
        if offset != missing_product_day:
            rows.append(f"{day.isoformat()},,商品A,{JAN},2,EAST")
        else:
            rows.append(f"{day.isoformat()},,商品B,4006381333931,4,EAST")
    (archive / "shipment.csv").write_bytes(("\n".join(rows) + "\n").encode("cp932"))
    return tmp_path / "Inbox"


def _setting(store, kind, value, expected_version=None):
    return store.append(
        change_type=kind, target="A1", value=value,
        effective_from=date(2026, 9, 1), actor="manager",
        reason_code="INITIAL_CONFIRMATION", comment="",
        application_version="test", expected_version=expected_version,
        changed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def test_trial_finishes_for_confirmed_subset_and_keeps_original_unit(tmp_path):
    inbox = _source(tmp_path)
    store = LocalSettingStore(tmp_path / "settings.sqlite3")
    _setting(store, "JAN_MAPPING", {"jan": JAN, "product_name": "商品A"})
    missing = trial_forecast(inbox, store, "A1")
    assert missing["status"] == "NEEDS_REVIEW"
    policy = _setting(store, "SHIPMENT_TRIAL_POLICY", {
        "unit": "BUNDLE", "missing_day": "OBSERVED_ONLY",
    })
    result = trial_forecast(inbox, store, "A1")
    assert result["status"] == "TRIAL_READY"
    assert result["unit"] == "BUNDLE"
    assert result["policy_version"] == policy["version"]
    assert result["series"][0]["days"][0]["source_quantity"] == 2.0
    assert len(result["series"][0]["days"]) == 7
    assert result == trial_forecast(inbox, store, "A1")
    assert result["product_code"] == "A1"
    try:
        trial_forecast(inbox, store, "B2")
    except ValueError as exc:
        assert str(exc) == "TRIAL_JAN_NOT_CONFIRMED"
    else:
        raise AssertionError("unconfirmed product must not be forecast")


def test_trial_route_requires_admin_token(tmp_path):
    inbox = _source(tmp_path)
    service = FieldPilotReadService(None, tmp_path / "config.json", inbox_root=inbox,
                                    learning_admin_token="secret")
    _setting(service.local_settings.store, "JAN_MAPPING",
             {"jan": JAN, "product_name": "商品A"})
    _setting(service.local_settings.store, "SHIPMENT_TRIAL_POLICY", {
        "unit": "CASE", "missing_day": "OBSERVED_ONLY",
    })
    app = create_app(SqliteRunStore(tmp_path / "api.sqlite3"),
                     SqliteCatalogStore(tmp_path / "api.sqlite3"), "api-secret",
                     field_pilot=service)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        url = "/api/field-pilot/admin/shipment-trial"
        assert client.post(url, json={"product_code": "A1"}).status_code == 403
        response = client.post(url, json={"product_code": "A1"}, headers={
            "X-Field-Pilot-Admin-Token": "secret",
        })
        assert response.status_code == 200
        trial = response.json()
        assert trial["status"] == "TRIAL_READY"
        preparation_url = "/api/field-pilot/admin/forecast-preparation"
        assert client.post(preparation_url, json={"product_code": "A1"}).status_code == 403
        preparation = client.post(preparation_url, json={"product_code": "A1"}, headers={
            "X-Field-Pilot-Admin-Token": "secret",
        })
        assert preparation.status_code == 200
        assert preparation.json()["formal_forecast_ready"] is False
        assert preparation.json()["preparation_candidate_count"] == 0
        feedback_url = url + "/feedback"
        assert client.post(feedback_url, json={
            "product_code": "A1", "source_fingerprint": trial["source_fingerprint"],
            "issue": "FORECAST_HIGH",
        }).status_code == 403
        assert client.post(feedback_url, json={
            "product_code": "A1", "source_fingerprint": trial["source_fingerprint"],
            "issue": "FORECAST_HIGH",
        }, headers={"X-Field-Pilot-Admin-Token": "secret"}).json()["status"] == "RECORDED"
        assert client.post(feedback_url, json={
            "product_code": "A1", "source_fingerprint": "0" * 64,
            "issue": "FORECAST_HIGH",
        }, headers={"X-Field-Pilot-Admin-Token": "secret"}).status_code == 409


def test_missing_day_policy_only_zeros_days_covered_by_a_daily_file(tmp_path):
    inbox = _source(tmp_path, missing_product_day=7, missing_file_day=14)
    store = LocalSettingStore(tmp_path / "settings.sqlite3")
    _setting(store, "JAN_MAPPING", {"jan": JAN, "product_name": "商品A"})
    first = _setting(store, "SHIPMENT_TRIAL_POLICY", {
        "unit": "CASE", "missing_day": "OBSERVED_ONLY",
    })
    observed = trial_forecast(inbox, store, "A1")
    _setting(store, "SHIPMENT_TRIAL_POLICY", {
        "unit": "CASE", "missing_day": "ZERO_WHEN_DAILY_FILE_PRESENT",
    }, expected_version=first["version"])
    zero = trial_forecast(inbox, store, "A1")
    assert observed["series"][0]["used_days_in_window"] == 26
    assert zero["series"][0]["used_days_in_window"] == 27
    assert observed["series"][0]["days"][0]["source_quantity"] == 2.0
    assert zero["series"][0]["days"][0]["source_quantity"] < 2.0
    assert observed["source_fingerprint"] != zero["source_fingerprint"]
