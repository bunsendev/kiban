"""構造学習と正式データ採用の分離、担当者・管理者の承認境界。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.field_pilot import FieldPilotReadService
from forecast_provider.field_pilot.inbox_classifier import classify_file
from forecast_provider.field_pilot.inbox_ledger import InboxLedger
from forecast_provider.field_pilot.inbox_processor import InboxProcessor
from forecast_provider.field_pilot.learning_service import LearningService
from forecast_provider.jobs import SqliteRunStore
from tests.test_field_pilot_unified_inbox import _policy, _stage


def _scan(root: Path, learning: LearningService):
    return InboxProcessor(
        root, learning.recognition_policy(), InboxLedger(root / "inbox.sqlite3"),
        review_observer=learning.consider,
    ).scan()


def test_optional_header_learning_is_idempotent_and_not_formal_import(tmp_path):
    _policy(tmp_path)
    root = tmp_path / "Inbox"
    root.mkdir()
    learning = LearningService(root, tmp_path / "inbox-policy.json")
    day = _policy(tmp_path)[1]
    _stage(root, "extra.csv", f"day,warehouse,cases,note\n{day},EAST,4,x\n".encode())
    _scan(root, learning)
    pending = learning.pending_view()["candidates"]
    assert len(pending) == 1
    assert pending[0]["suggested_kind"] == "WAREHOUSE_INVENTORY"
    assert pending[0]["risk"] == "LOW"
    candidate_id = pending[0]["candidate_id"]
    assert learning.operator_decide(candidate_id, "WAREHOUSE_INVENTORY")["status"] == "ACTIVE"
    assert learning.operator_decide(candidate_id, "WAREHOUSE_INVENTORY")["status"] == "ACTIVE"
    assert len(learning.store.list_contracts()) == 1
    assert len(learning.store.list_events()) == 1
    assert learning.pending_view()["pending_count"] == 0
    summary = InboxLedger(root / "inbox.sqlite3").summary(learning.base_policy(), day)
    assert summary["required"][0]["status"] == "RECEIVED"
    assert summary["status"] != "READY"
    next_file = root / "next.csv"
    next_file.write_text(f"day,warehouse,cases,note\n{day},EAST,5,y\n", encoding="utf-8")
    assert classify_file(
        next_file, next_file.name, learning.recognition_policy()
    ).status == "CONFIRMED"
    version = learning.store.list_contracts()[0]["learning_version"]
    learning.admin_deactivate(version, "admin")
    assert classify_file(
        next_file, next_file.name, learning.recognition_policy()
    ).status == "REVIEW_REQUIRED"
    restarted = LearningService(root, tmp_path / "inbox-policy.json")
    _stage(root, "later.csv", f"day,warehouse,cases,note\n{day},EAST,6,z\n".encode())
    _scan(root, restarted)
    assert restarted.pending_view()["pending_count"] == 1
    assert restarted.operator_decide(candidate_id, "WAREHOUSE_INVENTORY")["status"] == "ACTIVE"
    contracts = restarted.store.list_contracts()
    assert len(contracts) == 2
    assert {item["status"] for item in contracts} == {"ACTIVE", "INACTIVE"}
    assert contracts[0]["learning_version"] != contracts[1]["learning_version"]
    assert next(item for item in contracts if item["status"] == "ACTIVE")[
        "supersedes_version"
    ] == version


def test_major_change_requires_admin_and_validation(tmp_path):
    policy, day = _policy(tmp_path)
    root = tmp_path / "Inbox"
    root.mkdir()
    learning = LearningService(root, tmp_path / "inbox-policy.json")
    _stage(
        root, "novel.csv",
        f"日付,倉庫,在庫数量,商品コード,賞味期限\n{day},EAST,4,4900000000001,2026-10-31\n".encode(),
    )
    _scan(root, learning)
    candidate = learning.pending_view()["candidates"][0]
    assert candidate["risk"] == "MAJOR"
    cid = candidate["candidate_id"]
    assert learning.operator_decide(cid, "WAREHOUSE_INVENTORY")["status"] == "PENDING_ADMIN"
    assert learning.store.active_rules() == ()
    fields = {
        "date_column": "日付", "date_format": "%Y-%m-%d",
        "quantity_column": "在庫数量", "location_column": "倉庫",
        "jan_column": "商品コード", "expiry_column": "賞味期限",
        "source_unit": "在庫数量", "normalized_unit": "CASE",
        "location_id": "EAST", "mapping_version": None,
    }
    bad = {**fields, "quantity_column": "賞味期限"}
    try:
        learning.admin_approve(cid, "WAREHOUSE_INVENTORY", bad, "admin")
        raise AssertionError("invalid quantity must fail")
    except ValueError:
        pass
    assert learning.store.active_rules() == ()
    assert learning.store.get_candidate(candidate["candidate_id"])["status"] == "PENDING_ADMIN"
    assert learning.store.list_events()[0]["action"] == "VALIDATION_FAILED"
    assert learning.admin_approve(cid, "WAREHOUSE_INVENTORY", fields, "admin")["status"] == "ACTIVE"
    assert len(learning.store.active_rules()) == 1
    assert InboxLedger(root / "inbox.sqlite3").summary(policy, day)["status"] != "READY"


def test_field_pilot_learning_api_keeps_shadow_write_boundary(tmp_path):
    _policy_value, day = _policy(tmp_path)
    root = tmp_path / "Inbox"
    root.mkdir()
    learning = LearningService(root, tmp_path / "inbox-policy.json")
    _stage(root, "extra.csv", f"day,warehouse,cases,note\n{day},EAST,4,x\n".encode())
    _scan(root, learning)
    service = FieldPilotReadService(
        None, tmp_path / "pilot-settings.json", tmp_path / "inbox-policy.json",
        root, "admin-secret",
    )
    app = create_app(
        SqliteRunStore(tmp_path / "api.sqlite3"),
        SqliteCatalogStore(tmp_path / "api.sqlite3"), "api-secret",
        field_pilot=service,
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    candidate = client.get("/api/field-pilot/learning").json()["candidates"][0]
    cid = candidate["candidate_id"]
    assert client.get("/ui/pilot/admin").status_code == 200
    assert client.get("/api/field-pilot/admin").status_code == 403
    assert client.post("/api/field-pilot/admin/reject/" + cid, json={}).status_code == 403
    assert client.post("/api/field-shadow/preview", json={}).status_code == 405
    assert client.post(
        f"/api/field-pilot/learning/{cid}/confirm",
        json={"kind": "WAREHOUSE_INVENTORY"},
        headers={"Origin": "https://other.example"},
    ).status_code == 403
    response = client.post(
        f"/api/field-pilot/learning/{cid}/confirm",
        json={"kind": "WAREHOUSE_INVENTORY"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"
    assert "header_sha256" not in response.text
    assert client.get(
        "/api/field-pilot/admin", headers={"X-Field-Pilot-Admin-Token": "admin-secret"}
    ).status_code == 200
    assert client.get("/api/field-pilot/view").json()["status"] == "DATA_NOT_READY"
    assert client.get("/ui/assets/pilot_admin.js").status_code == 200
    assert "今日やること" in client.get("/ui/pilot").text


def test_learning_validation_reads_beyond_sample_before_activation(tmp_path):
    _policy(tmp_path)
    root = tmp_path / "Inbox"
    root.mkdir()
    learning = LearningService(root, tmp_path / "inbox-policy.json")
    day = _policy(tmp_path)[1]
    rows = [f"{day},EAST,4,x" for _ in range(100)] + [f"{day},EAST,-1,x"]
    _stage(root, "extended.csv", ("day,warehouse,cases,note\n" + "\n".join(rows)).encode())
    _scan(root, learning)
    candidate = learning.pending_view()["candidates"][0]
    try:
        learning.operator_decide(candidate["candidate_id"], "WAREHOUSE_INVENTORY")
        raise AssertionError("late invalid row must block activation")
    except ValueError:
        pass
    assert learning.store.active_rules() == ()
    assert learning.store.get_candidate(candidate["candidate_id"])["status"] == "PENDING_ADMIN"
