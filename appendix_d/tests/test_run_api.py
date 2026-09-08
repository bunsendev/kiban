"""Phase 1E run APIの契約試験。"""

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.jobs import SqliteRunStore


def payload():
    return {
        "experiment_id": "experiment-1",
        "condition_fingerprint": "fingerprint-1",
        "provider_id": "builtin-baseline",
        "model_name": "moving_average_28",
        "seed": 7,
        "origins": [{"origin_date": "2026-01-01", "cutoff_at": "2026-01-02T00:00:00+09:00"}],
        "expectations": [
            {
                "unique_id": "A",
                "origin_date": "2026-01-01",
                "target_date": "2026-01-02",
                "horizon": 1,
            }
        ],
    }


def client(tmp_path):
    api = TestClient(create_app(SqliteRunStore(tmp_path / "api.sqlite3"), "test-token"))
    api.headers["Authorization"] = "Bearer test-token"
    return api


def test_create_returns_202_and_status_is_queryable(tmp_path):
    api = client(tmp_path)
    response = api.post("/api/runs", json=payload())
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    status = api.get(f"/api/runs/{run_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "QUEUED"
    assert status.json()["origin_counts"] == {"QUEUED": 1}


def test_invalid_plan_is_422_and_unknown_run_is_404(tmp_path):
    api = client(tmp_path)
    invalid = payload()
    invalid["expectations"][0]["horizon"] = 2
    assert api.post("/api/runs", json=invalid).status_code == 422
    assert api.get("/api/runs/missing").status_code == 404
    assert api.post("/api/runs/missing/cancel").status_code == 404


def test_cancel_and_resume_condition_conflict(tmp_path):
    api = client(tmp_path)
    run_id = api.post("/api/runs", json=payload()).json()["run_id"]
    cancelled = api.post(f"/api/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["cancellation_requested"] is True
    assert cancelled.json()["status"] == "CANCELLED"
    conflict = api.post(f"/api/runs/{run_id}/resume", json={"condition_fingerprint": "different"})
    assert conflict.status_code == 409
    same = api.post(f"/api/runs/{run_id}/resume", json={"condition_fingerprint": "fingerprint-1"})
    assert same.status_code == 409


def test_same_condition_interrupted_run_can_resume(tmp_path):
    store = SqliteRunStore(tmp_path / "resume.sqlite3")
    api = TestClient(create_app(store, "test-token"))
    api.headers["Authorization"] = "Bearer test-token"
    run_id = api.post("/api/runs", json=payload()).json()["run_id"]
    store.start_or_resume(run_id, "fingerprint-1")
    lease = store.claim_next_origin(run_id, "stopped-worker", 60)
    assert lease is not None
    response = api.post(
        f"/api/runs/{run_id}/resume", json={"condition_fingerprint": "fingerprint-1"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "RUNNING"


def test_naive_cutoff_and_unknown_fields_are_rejected(tmp_path):
    api = client(tmp_path)
    invalid = payload()
    invalid["origins"][0]["cutoff_at"] = "2026-01-02T00:00:00"
    assert api.post("/api/runs", json=invalid).status_code == 422
    invalid = payload()
    invalid["extra"] = "forbidden"
    assert api.post("/api/runs", json=invalid).status_code == 422


def test_run_endpoints_require_bearer_token(tmp_path):
    api = TestClient(create_app(SqliteRunStore(tmp_path / "auth.sqlite3"), "secret"))
    assert api.get("/health").status_code == 200
    assert api.post("/api/runs", json=payload()).status_code == 401
