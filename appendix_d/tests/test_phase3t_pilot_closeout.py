"""Pilot closeout binds the latest evaluation decision to the final transition."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from forecast_provider.field_learning import SqliteFieldLearningStore
from portable.api.app import create_app
from portable.api.runtime_assignments import PortableRuntimeAssignments
from tests.test_phase3t_pilot_evaluation_gate import (
    _assessment,
    _decision,
    _fixture,
)


def _transition(application, assessment_revision=1):
    return {
        "expected_assessment_revision": assessment_revision,
        "expected_revision": application["revision"],
        "actor": "closeout-operator",
        "reason": "評価証跡と現場確認を照合した",
        "confirm_audited_transition": True,
    }


def _accepted(application, assessment_revision=1):
    return {
        **_transition(application, assessment_revision),
        "acceptance_results": [
            {"statement": item, "passed": True, "evidence": "Pilot実績で合格"}
            for item in application["proposal"]["acceptance_criteria"]
        ],
        "rollback_results": [
            {"statement": item, "triggered": False, "evidence": "発生なし"}
            for item in application["proposal"]["rollback_conditions"]
        ],
    }


def _rolled_back(application, assessment_revision=1):
    return {
        **_transition(application, assessment_revision),
        "rollback_target_version": application["proposal"]["rollback_target_version"],
        "backup_restored": True,
        "rollback_checks": [
            {"name": name, "passed": True, "evidence": "現場で確認"}
            for name in ("旧設定への復帰", "アプリとAPIの再起動", "既存データの参照")
        ],
    }


def _gate(client, application, runtime, decision):
    assessment = client.post(
        "/api/pilot-evaluation-gates", json=_assessment(application, runtime)
    ).json()
    decided = client.post(
        f"/api/pilot-evaluation-gates/{assessment['assessment_id']}/decisions",
        json=_decision(0, decision),
    )
    assert decided.status_code == 201
    return decided.json()


def test_passed_forward_decision_is_bound_to_acceptance_event(tmp_path) -> None:
    paths, application, runtime = _fixture(tmp_path)
    client = TestClient(create_app(paths.root), base_url="http://127.0.0.1")
    gate = _gate(client, application, runtime, "FORWARD_TO_ACCEPTANCE")
    closeout = client.get(f"/api/pilot-closeouts/{gate['assessment_id']}").json()
    assert closeout["action"] == "EVALUATE_ACCEPTANCE"

    direct = client.post(
        f"/api/change-applications/{application['application_id']}/acceptance",
        json=_accepted(closeout["application"]),
    )
    assert direct.status_code == 422
    assert "手順15-3" in direct.json()["detail"]

    response = client.post(
        f"/api/pilot-closeouts/{gate['assessment_id']}/acceptance",
        json=_accepted(closeout["application"]),
    )
    assert response.status_code == 201
    accepted = response.json()
    assert accepted["state"] == "ACCEPTED"
    reference = accepted["events"][-1]["evidence"]["pilot_evaluation_reference"]
    assert reference["assessment_id"] == gate["assessment_id"]
    assert reference["assessment_content_sha256"] == gate["content_sha256"]
    assert reference["decision_id"] == gate["decisions"][-1]["decision_id"]
    assert reference["decision_content_sha256"] == gate["decisions"][-1]["content_sha256"]
    assert reference["runtime_evaluation_sha256"] == gate["runtime_evaluation_sha256"]
    assert reference["decision"] == "FORWARD_TO_ACCEPTANCE"


def test_rollback_request_is_bound_to_verified_rollback(tmp_path) -> None:
    paths, application, runtime = _fixture(tmp_path)
    client = TestClient(create_app(paths.root), base_url="http://127.0.0.1")
    gate = _gate(client, application, runtime, "REQUEST_ROLLBACK")
    closeout = client.get(f"/api/pilot-closeouts/{gate['assessment_id']}").json()
    assert closeout["action"] == "EVALUATE_ROLLBACK"
    response = client.post(
        f"/api/pilot-closeouts/{gate['assessment_id']}/rollback",
        json=_rolled_back(closeout["application"]),
    )
    assert response.status_code == 201
    rolled_back = response.json()
    assert rolled_back["state"] == "ROLLED_BACK"
    reference = rolled_back["events"][-1]["evidence"]["pilot_evaluation_reference"]
    assert reference["decision"] == "REQUEST_ROLLBACK"
    assert reference["application_revision"] == 1


def test_acceptance_failure_can_complete_linked_rollback(tmp_path) -> None:
    paths, application, runtime = _fixture(tmp_path)
    client = TestClient(create_app(paths.root), base_url="http://127.0.0.1")
    gate = _gate(client, application, runtime, "FORWARD_TO_ACCEPTANCE")
    closeout = client.get(f"/api/pilot-closeouts/{gate['assessment_id']}").json()
    payload = _accepted(closeout["application"])
    payload["acceptance_results"][0]["passed"] = False
    failed = client.post(
        f"/api/pilot-closeouts/{gate['assessment_id']}/acceptance", json=payload
    ).json()
    assert failed["state"] == "ROLLBACK_REQUIRED"

    retry = client.get(f"/api/pilot-closeouts/{gate['assessment_id']}").json()
    assert retry["action"] == "EVALUATE_ROLLBACK"
    rolled_back = client.post(
        f"/api/pilot-closeouts/{gate['assessment_id']}/rollback",
        json=_rolled_back(retry["application"]),
    ).json()
    assert rolled_back["state"] == "ROLLED_BACK"
    assert (
        rolled_back["events"][-1]["evidence"]["pilot_evaluation_reference"][
            "assessment_id"
        ]
        == gate["assessment_id"]
    )


def test_non_forward_or_stale_decision_cannot_close_pilot(tmp_path) -> None:
    paths, application, runtime = _fixture(tmp_path)
    client = TestClient(create_app(paths.root), base_url="http://127.0.0.1")
    gate = _gate(client, application, runtime, "CONTINUE_PILOT")
    closeout = client.get(f"/api/pilot-closeouts/{gate['assessment_id']}").json()
    assert closeout["action"] == "NO_TRANSITION"
    blocked = client.post(
        f"/api/pilot-closeouts/{gate['assessment_id']}/acceptance",
        json=_accepted(closeout["application"]),
    )
    assert blocked.status_code == 422

    updated = client.post(
        f"/api/pilot-evaluation-gates/{gate['assessment_id']}/decisions",
        json=_decision(1, "FORWARD_TO_ACCEPTANCE"),
    )
    assert updated.status_code == 201
    stale = client.post(
        f"/api/pilot-closeouts/{gate['assessment_id']}/acceptance",
        json=_accepted(closeout["application"], assessment_revision=1),
    )
    assert stale.status_code == 409
    assert "更新" in stale.json()["detail"]


def test_pause_decision_stops_future_candidate_runs_but_preserves_history(tmp_path) -> None:
    paths, application, runtime = _fixture(tmp_path)
    client = TestClient(create_app(paths.root), base_url="http://127.0.0.1")
    assignments = PortableRuntimeAssignments(paths)
    before = assignments.resolve_execution(
        "before-pause", ["scope-v1"], "runtime-operator"
    )[0]
    assert before["status"] == "CANDIDATE_SELECTED"

    gate = _gate(client, application, runtime, "PAUSE_PILOT")
    closeout = client.get(f"/api/pilot-closeouts/{gate['assessment_id']}").json()
    assert closeout["action"] == "CONFIRM_PAUSE"
    payload = {
        **_transition(closeout["application"]),
        "confirm_future_runs_use_baseline": True,
        "confirm_existing_runs_unchanged": True,
    }
    response = client.post(
        f"/api/pilot-closeouts/{gate['assessment_id']}/pause", json=payload
    )
    assert response.status_code == 201
    paused = response.json()
    assert paused["state"] == "PAUSED"
    event = paused["events"][-1]
    assert event["transition"] == "PILOT_PAUSED"
    assert event["evidence"]["future_runtime"] == "BASELINE"
    assert event["evidence"]["existing_runs_unchanged"] is True
    reference = event["evidence"]["pilot_evaluation_reference"]
    assert reference["assessment_id"] == gate["assessment_id"]
    assert reference["assessment_content_sha256"] == gate["content_sha256"]
    assert reference["decision_id"] == gate["decisions"][-1]["decision_id"]
    assert reference["runtime_evaluation_sha256"] == gate["runtime_evaluation_sha256"]

    after = assignments.resolve_execution(
        "after-pause", ["scope-v1"], "runtime-operator"
    )[0]
    assert after["status"] == "BASELINE_SELECTED"
    assert after["reason_code"] == "PILOT_PAUSED"
    assert after["application_id"] is None
    history = assignments.overview()["resolutions"]
    assert any(item["resolution_id"] == before["resolution_id"] for item in history)
    assert any(item["resolution_id"] == after["resolution_id"] for item in history)


def test_pause_requires_both_operator_confirmations(tmp_path) -> None:
    paths, application, runtime = _fixture(tmp_path)
    client = TestClient(create_app(paths.root), base_url="http://127.0.0.1")
    gate = _gate(client, application, runtime, "PAUSE_PILOT")
    closeout = client.get(f"/api/pilot-closeouts/{gate['assessment_id']}").json()
    payload = {
        **_transition(closeout["application"]),
        "confirm_future_runs_use_baseline": True,
        "confirm_existing_runs_unchanged": False,
    }
    response = client.post(
        f"/api/pilot-closeouts/{gate['assessment_id']}/pause", json=payload
    )
    assert response.status_code == 422
    assert client.get(
        f"/api/change-applications/{application['application_id']}"
    ).json()["state"] == "PILOT_ACTIVE"


def test_existing_sqlite_event_table_is_migrated_without_losing_rows(tmp_path) -> None:
    database = tmp_path / "legacy.sqlite3"
    schema = Path("forecast_provider/field_learning/schema.sql").read_text("utf-8")
    schema = schema.replace(",'PILOT_PAUSED'", "").replace(",'PAUSED'", "")
    with sqlite3.connect(database) as db:
        db.executescript(schema)
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute(
            "INSERT INTO field_change_application_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "event-legacy", "application-legacy", 1,
                "PILOT_GATE_EVALUATED", "BLOCKED", "operator", "legacy",
                "{}", "2026-10-04T00:00:00+00:00", "2026-10-04T00:00:00+00:00",
                "a" * 64,
            ),
        )
    SqliteFieldLearningStore(database)
    with sqlite3.connect(database) as db:
        table_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE name='field_change_application_events'"
        ).fetchone()[0]
        assert "PILOT_PAUSED" in table_sql
        assert "PAUSED" in table_sql
        assert db.execute(
            "SELECT event_id FROM field_change_application_events"
        ).fetchone()[0] == "event-legacy"


def test_closeout_assets_are_available(tmp_path) -> None:
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert client.get("/pilot-closeouts.js").status_code == 200
    assert 'id="pilot-closeout-result"' in client.get("/").text
