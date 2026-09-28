"""未確定商品だけを現場管理画面へ出し、値の自動採用を防ぐ。"""

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.field_pilot.local_setting_store import LocalSettingStore
from forecast_provider.field_pilot.product_review import unresolved_products
from forecast_provider.field_pilot.read_model import FieldPilotReadService
from forecast_provider.jobs import SqliteRunStore


def test_unresolved_products_uses_only_local_confirmed_mapping(tmp_path):
    archive = tmp_path / "Inbox" / "Archive" / "ab" / "abcdef"
    archive.mkdir(parents=True)
    (archive / "stock.csv").write_bytes((
        "商品コード,商品名,明細倉庫コード,明細バラ数\n"
        "A1,商品A,EAST,4\nB2,商品B,EAST,5\n"
    ).encode("cp932"))
    (archive / "shipment.csv").write_bytes((
        "出荷日,商品コード,商品名,JAN,数量\n"
        "2026-09-01 0:00:00,,商品B,4901234567894,3\n"
    ).encode("cp932"))
    store = LocalSettingStore(tmp_path / "settings.sqlite3")
    store.append(
        change_type="JAN_MAPPING", target="A1",
        value={"jan": "4006381333931", "product_name": "商品A"},
        effective_from=date(2026, 9, 1), actor="manager",
        reason_code="INITIAL_CONFIRMATION", comment="", application_version="test",
        expected_version=None, changed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    result = unresolved_products(tmp_path / "Inbox", store)
    assert result["items"] == [{
        "product_code": "B2", "product_name": "商品B",
        "candidate_jans": ["4901234567894"], "candidate_status": "UNIQUE",
        "direct_code_match": False,
        "readiness": {"trial_eligible": False, "blocking_reasons": [
            "JAN_UNCONFIRMED", "SHIPMENT_HISTORY_MISSING",
            "SHIPMENT_UNIT_UNCONFIRMED", "MISSING_DAY_POLICY_UNCONFIRMED",
        ]},
    }]
    assert result["unresolved_count"] == 1
    assert result["confirmed_items"] == [{
        "product_code": "A1", "jan": "4006381333931",
        "observed_shipment_days": 0,
        "evidence_status": "SHIPMENT_HISTORY_MISSING",
        "readiness": {"trial_eligible": False, "blocking_reasons": [
            "SHIPMENT_HISTORY_MISSING", "SHIPMENT_UNIT_UNCONFIRMED",
            "MISSING_DAY_POLICY_UNCONFIRMED",
        ]},
        "trial_policy": None,
    }]
    assert result["file_count"] == 2
    assert result["complete"] is True


def test_unresolved_products_requires_admin_token(tmp_path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    service = FieldPilotReadService(None, tmp_path / "pilot-settings.json",
                                    inbox_root=inbox, learning_admin_token="admin-secret")
    app = create_app(SqliteRunStore(tmp_path / "api.sqlite3"),
                     SqliteCatalogStore(tmp_path / "api.sqlite3"), "api-secret",
                     field_pilot=service)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        path = "/api/field-pilot/admin/unresolved-products"
        assert client.get(path).status_code == 403
        allowed = client.get(path, headers={"X-Field-Pilot-Admin-Token": "admin-secret"})
        assert allowed.status_code == 200
        assert allowed.json()["items"] == []
        publish = "/api/field-pilot/admin/product-mapping/publish"
        denied = client.post(publish, json={"actor": "manager", "reason": "確認済み"})
        assert denied.status_code == 403
        response = client.post(
            publish, json={"actor": "manager", "reason": "確認済み"},
            headers={"X-Field-Pilot-Admin-Token": "admin-secret"},
        )
        assert response.status_code == 409


def test_name_match_candidate_remains_unconfirmed(tmp_path):
    archive = tmp_path / "Inbox" / "Archive" / "ab" / "abcdef"
    archive.mkdir(parents=True)
    (archive / "stock.csv").write_bytes((
        "商品コード,商品名,明細倉庫コード,明細バラ数\n"
        "A1,同名商品,EAST,4\nB2,候補なし,EAST,5\n"
    ).encode("cp932"))
    (archive / "shipment.csv").write_bytes((
        "出荷日,商品コード,商品名,JAN,数量\n"
        "2026-09-01,DIFFERENT,同名商品,4901234567894,3\n"
    ).encode("cp932"))
    result = unresolved_products(
        tmp_path / "Inbox", LocalSettingStore(tmp_path / "settings.sqlite3"),
    )
    assert result["confirmed_count"] == 0
    assert result["items"][0]["candidate_status"] == "UNIQUE"
    assert result["items"][0]["direct_code_match"] is False
    assert result["items"][1]["candidate_status"] == "MISSING"


def test_confirmed_jan_finds_history_when_shipment_code_is_blank(tmp_path):
    archive = tmp_path / "Inbox" / "Archive" / "ab" / "abcdef"
    archive.mkdir(parents=True)
    (archive / "stock.csv").write_bytes((
        "商品コード,商品名,明細倉庫コード,明細バラ数\nA1,商品A,EAST,4\n"
    ).encode("cp932"))
    (archive / "shipment.csv").write_bytes((
        "出荷日,商品コード,商品名,JAN,数量\n"
        "2026/09/01 0:00:00,,商品A,4901234567894,3\n"
    ).encode("cp932"))
    store = LocalSettingStore(tmp_path / "settings.sqlite3")
    store.append(
        change_type="JAN_MAPPING", target="A1",
        value={"jan": "4901234567894", "product_name": "商品A"},
        effective_from=date(2026, 9, 1), actor="manager",
        reason_code="INITIAL_CONFIRMATION", comment="", application_version="test",
        expected_version=None, changed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    result = unresolved_products(tmp_path / "Inbox", store)
    assert result["confirmed_items"][0]["observed_shipment_days"] == 1
    assert result["confirmed_items"][0]["evidence_status"] == "HISTORY_REVIEW_REQUIRED"
