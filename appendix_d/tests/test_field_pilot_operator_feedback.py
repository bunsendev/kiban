"""担当者の選択式操作記録は原値を受け取らず、Policyで集計共有する。"""

import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.feedback_sync.policy import DEFAULT_FLAGS
from forecast_provider.feedback_sync.privacy import collect_events, minimize
from forecast_provider.field_pilot.inbox_ledger import InboxLedger
from forecast_provider.field_pilot.inbox_policy import InboxPolicy
from forecast_provider.field_pilot.inbox_processor import InboxProcessor
from forecast_provider.field_pilot.read_model import FieldPilotReadService
from forecast_provider.jobs import SqliteRunStore
from tests.test_field_pilot_unified_inbox import _stage


def test_operator_feedback_is_local_structured_and_policy_gated(tmp_path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    service = FieldPilotReadService(None, tmp_path / "pilot-settings.json",
                                    inbox_root=inbox)
    app = create_app(SqliteRunStore(tmp_path / "api.sqlite3"),
                     SqliteCatalogStore(tmp_path / "api.sqlite3"), "api-secret",
                     field_pilot=service)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        path = "/api/field-pilot/operator-feedback"
        value = {"step": "RESULT", "issue": "NOT_UPDATED"}
        assert client.post(path, json=value).status_code == 403
        assert client.post(path, json=value, headers={
            "Origin": "https://other.example", "X-Field-Pilot-Operator": "1",
        }).status_code == 403
        assert client.post(path, json={**value, "filename": "secret.csv"}, headers={
            "X-Field-Pilot-Operator": "1",
        }).status_code == 422
        assert client.post(path, json={"step": "RAW_JAN", "issue": "OTHER"}, headers={
            "X-Field-Pilot-Operator": "1",
        }).status_code == 422
        accepted = client.post(path, json=value, headers={
            "X-Field-Pilot-Operator": "1",
        })
        assert accepted.status_code == 200
        assert accepted.json() == {"status": "RECORDED"}
        action = client.post("/api/field-pilot/operator-action",
                             json={"action": "DETAIL_OPENED"}, headers={
                                 "X-Field-Pilot-Operator": "1",
                             })
        assert action.status_code == 200

    with sqlite3.connect(inbox / "improvement-events.sqlite3") as db:
        rows = db.execute(
            "SELECT event_type,error_code,jan,location_id,metrics_json "
            "FROM improvement_events WHERE event_type LIKE 'OPERATOR_%' "
            "ORDER BY event_type",
        ).fetchall()
    assert rows == [
        ("OPERATOR_ACTION", "ACTION_DETAIL_OPENED", None, None, "{}"),
        ("OPERATOR_FEEDBACK", "OPERATOR_RESULT_NOT_UPDATED", None, None, "{}"),
    ]
    day = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    events = collect_events(inbox / "improvement-events.sqlite3", day)
    off = minimize(events, {"level": 0, "flags": DEFAULT_FLAGS.copy()}, client_id="pilot")
    assert off["event_counts"] == []
    flags = DEFAULT_FLAGS.copy()
    flags["diagnostics"] = True
    shared = minimize(events, {"level": 2, "flags": flags}, client_id="pilot")
    assert {item["error_code"] for item in shared["event_counts"]} == {
        "ACTION_DETAIL_OPENED", "OPERATOR_RESULT_NOT_UPDATED",
    }
    assert "secret.csv" not in json.dumps(shared)
    assert shared["details"] == []


def test_unconfigured_policy_shows_safe_intake_counts_without_ready(tmp_path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    _stage(inbox, "trial.csv", b"day,warehouse,cases\n2026-09-28,EAST,3\n")
    policy = InboxPolicy("UNCONFIGURED", (), ())
    assert InboxProcessor(inbox, policy, InboxLedger(inbox / "inbox.sqlite3")).scan() == 1
    policy_path = tmp_path / "inbox-policy.json"
    policy_path.write_text(json.dumps({
        "format": "field-pilot-inbox-v1", "version": "UNCONFIGURED",
        "required": [], "rules": [],
    }), encoding="utf-8")
    service = FieldPilotReadService(
        None, tmp_path / "pilot-settings.json", policy_path, inbox,
    )
    summary = service.inbox_view()
    assert summary["status"] == "SETUP_REQUIRED"
    assert summary["checked_count"] == 1
    assert summary["review_count"] == 1
    assert summary["required"] == []
    assert service.view()["status"] == "DATA_NOT_READY"
