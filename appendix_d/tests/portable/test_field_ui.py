"""Four-step workflow acceptance using synthetic inventory and shipments."""

import csv
import io
import time
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from test_p1_flow import pilot_forecast_zip

from portable.api.app import create_app
from portable.api.field_read_model import export, page, with_reviews
from portable.api.field_store import FieldStore
from portable.api.result_feedback import FeedbackConflict


def wait_job(client, job):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = next(v for v in client.get("/api/field/jobs").json() if v["id"] == job["id"])
        if value["status"] != "RUNNING":
            return value
        time.sleep(0.05)
    pytest.fail("field job did not finish")


def test_upload_forecast_period_review_export_and_resume(tmp_path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert client.get("/field").status_code == 200
    assert client.get("/").status_code == 200
    started = client.post(
        "/api/field/upload", content=pilot_forecast_zip(), headers={"x-file-name": "synthetic.zip"}
    )
    assert started.status_code == 202
    job = wait_job(client, started.json())
    assert job["status"] == "SUCCEEDED", job
    analysis_id = job["analysis_id"]
    assert (
        client.post(
            f"/api/business-archives/{analysis_id}/formal-inventory",
            json={
                "actor": "synthetic",
                "reason": "synthetic CASE confirmed",
                "confirm_case": True,
                "locations": [
                    {
                        "source_center": "神戸",
                        "location_code": "KOBE",
                        "location_name": "神戸倉庫",
                        "snapshot_time": "16:00",
                    }
                ],
            },
        ).status_code
        == 201
    )
    started = client.post(
        f"/api/field/{analysis_id}/advance",
        json={
            "actor": "synthetic",
            "reason": "synthetic scope verified",
            "confirm_pilot_scope": True,
            "confirm_quantity_reconciliation": True,
            "confirm_identity_bridge": True,
            "confirm_zero_policy": True,
        },
    )
    assert started.status_code == 202, started.text
    assert wait_job(client, started.json())["status"] == "SUCCEEDED"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = client.get(f"/api/daily-runs/{analysis_id}").json()
        if state["status"] != "PRODUCTION_RUNNING":
            break
        time.sleep(0.05)
    result = client.get(f"/api/field/{analysis_id}/results")
    assert result.status_code == 200, result.text
    key = result.json()["result_id"]
    endpoint = f"/api/field/results/{key}"
    value = client.get(endpoint).json()
    assert value["counts"]["total"] == 10
    assert value["counts"]["ok"] == 0  # No expiry policy; never green.
    assert value["counts"]["pending"] == 10
    assert client.get(endpoint + "?limit=3").json()["counts"]["total"] == 10
    row = value["rows"][0]
    payload = {
        "item": row["item"],
        "actor": "synthetic",
        "choice": "CHANGE",
        "quantity": 0,
        "reason": "synthetic correction",
        "revision": 0,
    }
    saved = client.post(endpoint + "/review", json=payload)
    assert saved.status_code == 201, saved.text
    assert client.post(endpoint + "/review", json=payload).status_code == 409
    original = client.get(endpoint).json()["rows"][0]
    assert original["forecast"] == row["forecast"]
    assert original["review"]["quantity"] == 0
    for r in value["rows"][1:]:
        assert (
            client.post(
                endpoint + "/review",
                json={
                    "item": r["item"],
                    "actor": "synthetic",
                    "choice": "HOLD",
                    "reason": "need field confirmation",
                },
            ).status_code
            == 201
        )
    counts = client.get(endpoint + "/next-review").json()["counts"]
    assert counts["complete"] and counts["held"] == 9 and counts["saved"] == 1
    data = client.post(endpoint + "/download", json={"selected": [row["item"]]})
    records = list(csv.reader(io.StringIO(data.content.decode("utf-8-sig"))))
    assert len(records) == 2 and records[1][7] == "0"
    ticket = client.post(endpoint + "/export", json={"selected": [row["item"]]})
    assert ticket.status_code == 201
    streamed = client.get(ticket.json()["download_href"])
    assert streamed.content == data.content
    assert "attachment" in streamed.headers["content-disposition"]
    assert client.post(endpoint + "/download", json={"selected": ["unknown"]}).status_code == 422
    assert (
        client.post(
            "/api/field/feedback",
            json={"step": 4, "analysis_id": analysis_id, "comment": "synthetic UI observation"},
        ).status_code
        == 201
    )
    # Same immutable result can be reopened after app restart; observations remain.
    second = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert second.get(endpoint).json()["counts"] == counts
    assert len(second.get(endpoint + "/history").json()) == 10
    assert second.get("/api/field/versions").json()[0]["result_id"] == key
    assert second.post(endpoint + "/issues-download", json={}).status_code == 200
    # A later expiry policy creates a separate result, not a mutation of this review queue.
    summary = second.post(
        f"/api/daily-runs/{analysis_id}/daily-summary",
        json={
            "actor": "synthetic",
            "reason": "expiry policy verified",
            "minimum_remaining_days": 0,
            "attention_days": 7,
            "confirm_expiry_policy": True,
        },
    )
    assert summary.status_code == 201, summary.text
    updated = second.get(f"/api/field/{analysis_id}/results").json()["result_id"]
    assert updated != key
    assert second.get(endpoint).json()["counts"] == counts
    evaluated = second.get(f"/api/field/results/{updated}").json()
    assert evaluated["counts"]["action"] > 0


def test_invalid_upload_and_interrupted_job(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1")
    job = client.post("/api/field/upload", content=b"invalid").json()
    assert wait_job(client, job)["status"] == "FAILED"
    app.state.field_store.put_job({"id": "synthetic", "status": "RUNNING", "created_at": "2026"})
    store = FieldStore(app.state.field_store.path)
    assert next(v for v in store.jobs() if v["id"] == "synthetic")["status"] == "INTERRUPTED"


def test_large_paging_reviews_do_not_hide_blocked_or_resolve_risks(tmp_path):
    store = FieldStore(tmp_path / "field.db")
    rows = [
        {
            "item": str(i),
            "jan": str(i),
            "name": "synthetic",
            "warehouse": "A",
            "inventory_date": "2026-01-01",
            "unit": "箱",
            "period": [],
            "forecast": None,
            "category": "CHECK",
            "reasons": ["予測できません"],
        }
        for i in range(1100)
    ]
    value = {"result_id": "synthetic", "rows": rows}
    assert len(page(with_reviews(value, store), offset=1090)["rows"]) == 10
    assert page(with_reviews(value, store), query="1099")["counts"]["pending"] == 1100
    with pytest.raises(ValueError):
        store.save("synthetic", rows[0], {"actor": "A", "choice": "ACCEPT"})
    observation = {"actor": "A", "choice": "HOLD", "reason": "=formula"}
    store.save("synthetic", rows[0], observation)
    with pytest.raises(FeedbackConflict):
        store.save("synthetic", rows[0], observation)
    current = with_reviews(value, store)
    assert current["counts"]["held"] == 1 and current["counts"]["check"] == 1100
    assert "'=formula" in export(current, ["0"]).decode("utf-8-sig")


def test_event_boundary_and_false_completion_rejected(tmp_path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    payload = {
        "event_id": str(uuid.uuid4()),
        "flow_session_id": str(uuid.uuid4()),
        "screen": "field",
        "event_name": "STEP_VIEWED",
        "step": 3,
        "sequence": 1,
        "outcome": "INFO",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    assert client.post("/api/field/events", json=payload).status_code == 201
    assert client.post("/api/field/events", json=payload).status_code == 201
    assert (
        client.post(
            "/api/field/events", json=payload | {"event_name": "STEP_COMPLETED"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/field/events", json=payload, headers={"Origin": "https://outside.example"}
        ).status_code
        == 403
    )
    assert client.post("/api/field/feedback", json=[]).status_code == 422
    assert client.get("/api/field/results/invalid").status_code == 404
