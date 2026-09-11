"""Phase 1S lifecycle APIの監査主体と操作フロー。"""

from fastapi.testclient import TestClient
from test_lifecycle_service import fixture

from forecast_provider.api import create_app
from forecast_provider.lifecycle import SqliteLifecycleStore


def test_lifecycle_api_uses_authenticated_actor_and_exposes_current_state(tmp_path):
    service, _, runs, catalog, evaluations, _, request = fixture(tmp_path)
    lifecycle = SqliteLifecycleStore(tmp_path / "api-lifecycle.sqlite3")
    api = TestClient(
        create_app(
            runs,
            catalog,
            "token",
            acceptance=object(),
            evaluation_registry=evaluations,
            reporting=service.reporting,
            report_root=tmp_path,
            lifecycle=lifecycle,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    payload = {
        **request,
        "trial_start_date": request["trial_start_date"].isoformat(),
        "created_by": "forged@example.test",
    }

    created = api.post("/api/lifecycle-plans", json=payload)

    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["created_by"] == "local-admin"
    scheduled = api.post("/api/lifecycle-schedule")
    assert scheduled.status_code == 200
    cycle_id = scheduled.json()["cycle_ids"][0]
    completed = api.post(
        f"/api/lifecycle-cycles/{cycle_id}/complete",
        json={"challenger_run_id": "challenger", "comparison_id": "comparison-cycle"},
    )
    assert completed.status_code == 200 and completed.json()["status"] == "READY"
    promoted = api.post(
        f"/api/lifecycle-cycles/{cycle_id}/promote",
        json={"expected_revision": 1, "reason": "基準を満たした"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["approved_by"] == "local-admin"
    status = api.get(f"/api/lifecycle-plans/{plan['plan_id']}")
    assert status.status_code == 200
    assert status.json()["champion"]["to_run_id"] == "challenger"
    assert [event["action"] for event in status.json()["champion_events"]] == [
        "INITIALIZED",
        "PROMOTED",
    ]


def test_lifecycle_api_rejects_unauthenticated_mutation(tmp_path):
    service, _, runs, catalog, evaluations, _, request = fixture(tmp_path)
    app = create_app(
        runs,
        catalog,
        "token",
        acceptance=object(),
        evaluation_registry=evaluations,
        reporting=service.reporting,
        report_root=tmp_path,
        lifecycle=SqliteLifecycleStore(tmp_path / "api-auth.sqlite3"),
    )
    payload = {**request, "trial_start_date": request["trial_start_date"].isoformat()}

    with TestClient(app) as anonymous:
        assert anonymous.post("/api/lifecycle-plans", json=payload).status_code == 401
