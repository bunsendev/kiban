import csv
import io

import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.api.result_feedback import FeedbackConflict, ResultFeedback, export_results

ROWS = [
    {"unique_id": "JAN-A@倉庫1", "target_date": "2026-10-06", "yhat": 12},
    {"unique_id": "=BAD()", "target_date": "2026-10-06", "yhat": 5},
]
PAYLOAD = {
    "unique_id": "JAN-A@倉庫1",
    "target_date": "2026-10-06",
    "quantity": 0,
    "actor": "担当者",
    "reason": "休業",
    "comment": "=BAD()",
    "rating": "HIGH",
}


def test_feedback_append_only_conflict_and_export(tmp_path):
    path = tmp_path / "feedback.sqlite3"
    ledger = ResultFeedback(path)
    first = ledger.save("production:a", ROWS, PAYLOAD, {"mode": "FIELD"})
    assert first["original_quantity"] == 12
    with pytest.raises(FeedbackConflict):
        ledger.save("production:a", ROWS, PAYLOAD, None)
    second = ledger.save(
        "production:a",
        ROWS,
        PAYLOAD | {"revision": first["revision"], "quantity": None, "rating": "OK"},
        None,
    )
    reopened = ResultFeedback(path)
    view = reopened.view("production:a", ROWS)
    assert len(view["history"]) == 2
    assert ROWS[0]["yhat"] == 12
    assert view["rows"][0]["feedback"]["revision"] == second["revision"]
    assert reopened.history("production:b") == []
    exported = list(csv.reader(io.StringIO(export_results(view).decode("utf-8-sig"))))
    assert exported[1][2:5] == ["12", "", "12"]
    assert exported[1][7] == "'=BAD()"
    assert exported[2][0] == "'=BAD()"
    assert (
        len(
            list(csv.reader(io.StringIO(export_results(view, ["JAN-A@倉庫1"]).decode("utf-8-sig"))))
        )
        == 2
    )
    with pytest.raises(ValueError):
        export_results(view, [])
    with pytest.raises(ValueError):
        export_results(view, ["missing"])


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": -1},
        {"quantity": float("nan")},
        {"quantity": True},
        {"quantity": 10, "reason": " "},
        {"actor": ""},
        {"unique_id": "missing"},
        {"rating": "invalid"},
        {"revision": "0"},
    ],
)
def test_invalid_feedback_is_not_saved(tmp_path, change):
    ledger = ResultFeedback(tmp_path / "feedback.sqlite3")
    with pytest.raises(ValueError):
        ledger.save("run:a", ROWS, PAYLOAD | change, None)
    assert ledger.history("run:a") == []


def test_routes_preserve_prediction_and_restart(tmp_path, monkeypatch):
    monkeypatch.setattr("portable.api.app.forecast", lambda *args: ROWS)
    content = "ds,unique_id,y\n" + "".join(f"2026-09-{n:02d},a,1\n" for n in range(1, 9))
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        response = client.post("/api/runs", content=content, headers={"Content-Type": "text/csv"})
        assert response.status_code == 201, response.text
        run = response.json()
        url = f"/api/operator-results/run/{run['run_id']}"
        saved = client.post(url + "/feedback", json=PAYLOAD)
        assert saved.status_code == 201, saved.text
        assert client.post(url + "/feedback", json=PAYLOAD).status_code == 409
        assert (
            client.get(f"/api/runs/{run['run_id']}").json()["result_sha256"] == run["result_sha256"]
        )
        assert client.post(url + "/download", json={"selected": ["JAN-A@倉庫1"]}).status_code == 200
        assert client.get("/operator-results.js").status_code == 200
        assert client.get("/api/operator-results/other/x").status_code == 404
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        assert client.get(url).json()["rows"][0]["feedback"]["quantity"] == 0
        assert client.get(f"/api/runs/{run['run_id']}").json()["predictions"] == ROWS
