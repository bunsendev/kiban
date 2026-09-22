"""担当者画面の操作改善eventと、収集しない情報の境界。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.operation_events import SqliteOperationEventStore


def _payload(event_name="CONNECTED", sequence=1, **metadata):
    return {
        "event_id": str(uuid4()),
        "flow_session_id": str(uuid4()),
        "screen": "easy",
        "event_name": event_name,
        "step": 1,
        "sequence": sequence,
        "outcome": "FAILURE" if event_name == "ANALYSIS_FAILED" else "SUCCESS",
        "elapsed_ms": 1_250,
        "metadata": {"flow_version": "easy-v1", **metadata},
        "occurred_at": datetime.now(UTC).isoformat(),
    }


def _client(tmp_path):
    database = tmp_path / "operation-events.sqlite3"
    store = SqliteOperationEventStore(database)
    app = create_app(
        SqliteRunStore(database),
        SqliteCatalogStore(database),
        "token",
        operation_events=store,
    )
    return TestClient(app), store


def test_operation_events_are_idempotent_and_summarized(tmp_path):
    client, _store = _client(tmp_path)
    headers = {"Authorization": "Bearer token"}
    session_id = str(uuid4())
    events = [
        _payload("CONNECTED", 1),
        _payload("SOURCE_SELECTED", 2, source_mode="upload", file_kind="zip"),
        _payload("ANALYSIS_REQUESTED", 3, source_mode="upload"),
        _payload("ANALYSIS_ACCEPTED", 4, source_mode="upload", mapping_match=True),
    ]
    for event in events:
        event["flow_session_id"] = session_id
        assert client.post("/api/operation-events", json=event, headers=headers).status_code == 201

    duplicate = client.post("/api/operation-events", json=events[-1], headers=headers)
    assert duplicate.status_code == 201
    summary = client.get("/api/operation-events/summary?days=7", headers=headers).json()
    assert summary["total_events"] == 4
    assert summary["session_count"] == 1
    assert summary["operator_count"] == 1
    assert summary["funnel"] == {
        "CONNECTED": 1,
        "SOURCE_SELECTED": 1,
        "ANALYSIS_REQUESTED": 1,
        "ANALYSIS_ACCEPTED": 1,
    }
    assert summary["source_modes"] == {"upload": 3}


def test_operation_events_reject_raw_or_identifying_metadata(tmp_path):
    client, _store = _client(tmp_path)
    headers = {"Authorization": "Bearer token"}
    for forbidden in ("filename", "file_path", "token", "file_content", "free_text"):
        response = client.post(
            "/api/operation-events",
            json=_payload("SOURCE_SELECTED", **{forbidden: "secret.csv"}),
            headers=headers,
        )
        assert response.status_code == 422
        assert "記録できない操作情報" in response.json()["message"]


def test_operation_event_access_export_and_retention(tmp_path):
    client, store = _client(tmp_path)
    headers = {"Authorization": "Bearer token"}
    failed = _payload(
        "ANALYSIS_FAILED",
        source_mode="folder",
        error_kind="mapping_not_found",
    )
    assert client.post("/api/operation-events", json=failed, headers=headers).status_code == 201
    assert client.get("/api/operation-events").status_code == 401
    listed = client.get("/api/operation-events?days=7", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["subject"] == "local-admin"

    exported = client.get("/api/operation-events/export.csv?days=7", headers=headers)
    assert exported.status_code == 200
    assert "mapping_not_found" in exported.text
    assert "secret.csv" not in exported.text

    assert store.purge_before(datetime.now(UTC) + timedelta(seconds=1)) == 1
    assert store.list_events(limit=10) == []
