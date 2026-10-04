"""Pilot evaluation gates require fixed same-Actual evidence and a human decision."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from forecast_provider.field_learning import (
    SqliteFieldLearningStore,
    build_actual_outcome_event,
)
from portable.api.app import create_app
from portable.api.learning_reviews import PortableWeeklyLearningReviews
from portable.api.runtime_assignments import PortableRuntimeAssignments
from portable.api.runtime_weekly_evaluations import PortableRuntimeWeeklyEvaluations
from portable.runtime.paths import DataPaths
from tests.test_phase3t_runtime_assignment_resolver import _activate
from tests.test_phase3t_runtime_weekly_evaluations import _case, _jan, _receipt


def _actual(store, case) -> None:
    now = datetime.now(UTC)
    value = build_actual_outcome_event(
        case_id=case.case_id,
        expected_revision=0,
        source_version="actual-v1",
        source_sha256="9" * 64,
        actual_shipped_quantity="11",
        actual_demand_quantity="12",
        stockout_quantity="0",
        expired_quantity="0",
        interwarehouse_transfer_quantity="0",
        known_at=now,
        recorded_at=now,
    )
    store.append_actual_outcome(value, 0)


def _fixture(tmp_path):
    paths = DataPaths(tmp_path)
    paths.ensure()
    application, _ = _activate(paths)
    assignments = PortableRuntimeAssignments(paths)
    baseline = assignments.resolve_execution("build-baseline", ["scope-v2"], "operator")[0]
    candidate = assignments.resolve_execution("build-candidate", ["scope-v1"], "operator")[0]
    _receipt(paths, "build-baseline", "run-baseline", baseline)
    _receipt(paths, "build-candidate", "run-candidate", candidate)
    store = SqliteFieldLearningStore(paths.state / "shipment-actual-outcomes.sqlite3")
    jan = _jan(950)
    left = _case(store, run_id="run-baseline", scope="scope-v2", forecast="15", jan=jan)
    right = _case(store, run_id="run-candidate", scope="scope-v1", forecast="13", jan=jan)
    _actual(store, left)
    _actual(store, right)
    weekly = PortableWeeklyLearningReviews(paths.state / "shipment-actual-outcomes.sqlite3").create(
        {
            "week_end": "2026-09-27",
            "pilot_scope_versions": ["scope-v1", "scope-v2"],
            "aggregation_version": "weekly-v1",
            "threshold_version": "threshold-v1",
            "minimum_evidence_count": 1,
            "reviewer": "reviewer",
            "known_at": datetime.now(UTC).isoformat(),
            "confirm_shadow_review": True,
        }
    )
    runtime = PortableRuntimeWeeklyEvaluations(paths).create(
        {
            "weekly_review_id": weekly["review_id"],
            "evaluation_version": "runtime-weekly-v1",
            "reviewer": "reviewer",
            "confirm_same_actual_shadow": True,
        }
    )
    return paths, application, runtime


def _assessment(application, runtime, minimum_count=1):
    return {
        "application_id": application["application_id"],
        "runtime_evaluation_id": runtime["evaluation_id"],
        "policy_version": "pilot-evaluation-v1",
        "minimum_observation_days": 7,
        "minimum_same_actual_count": minimum_count,
        "maximum_unattributed_ratio": "0",
        "maximum_mae_delta_cases": "0",
        "maximum_wape_delta": "0",
        "maximum_operator_change_ratio": "1",
        "maximum_stockout_cases": "0",
        "maximum_expired_cases": "0",
        "maximum_interwarehouse_transfer_cases": "0",
        "reviewer": "pilot-reviewer",
        "confirm_advisory_only": True,
    }


def _decision(revision, decision):
    return {
        "expected_revision": revision,
        "decision": decision,
        "actor": "pilot-reviewer",
        "reason": "固定した根拠に基づく判断",
        "confirm_no_automatic_action": True,
    }


def test_passed_gate_can_be_forwarded_without_applying_configuration(tmp_path) -> None:
    _, application, runtime = _fixture(tmp_path)
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    response = client.post("/api/pilot-evaluation-gates", json=_assessment(application, runtime))
    assert response.status_code == 201
    value = response.json()
    assert value["report"]["status"] == "PASSED"
    assert value["report"]["recommended_action"] == "FORWARD_TO_ACCEPTANCE"
    assert all(item["passed"] for item in value["report"]["checks"])

    decided = client.post(
        f"/api/pilot-evaluation-gates/{value['assessment_id']}/decisions",
        json=_decision(0, "FORWARD_TO_ACCEPTANCE"),
    )
    assert decided.status_code == 201
    result = decided.json()
    assert result["revision"] == 1
    assert result["latest_decision"] == "FORWARD_TO_ACCEPTANCE"
    unchanged = client.get(f"/api/change-applications/{application['application_id']}").json()
    assert unchanged["state"] == "PILOT_ACTIVE"
    assert unchanged["revision"] == 1

    restarted = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert restarted.get(f"/api/pilot-evaluation-gates/{value['assessment_id']}").json() == result
    assert "15-3. Pilot結果を基準に沿って判断" in restarted.get("/").text
    assert restarted.get("/pilot-evaluation-gates.js").status_code == 200


def test_insufficient_evidence_blocks_forward_and_detects_decision_tampering(tmp_path) -> None:
    paths, application, runtime = _fixture(tmp_path)
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    value = client.post(
        "/api/pilot-evaluation-gates", json=_assessment(application, runtime, 2)
    ).json()
    assert value["report"]["status"] == "BLOCKED"
    assert value["report"]["recommended_action"] == "CONTINUE_PILOT"
    rejected = client.post(
        f"/api/pilot-evaluation-gates/{value['assessment_id']}/decisions",
        json=_decision(0, "FORWARD_TO_ACCEPTANCE"),
    )
    assert rejected.status_code == 422
    accepted = client.post(
        f"/api/pilot-evaluation-gates/{value['assessment_id']}/decisions",
        json=_decision(0, "CONTINUE_PILOT"),
    )
    assert accepted.status_code == 201

    folder = paths.state / "PilotEvaluationDecisions"
    target = next(folder.glob("*.json"))
    target.write_bytes(target.read_bytes().replace(b"CONTINUE_PILOT", b"PAUSE_PILOT   "))
    loaded = client.get(f"/api/pilot-evaluation-gates/{value['assessment_id']}")
    assert loaded.status_code == 404
    assert "整合性" in loaded.json()["detail"]


def test_failed_quality_threshold_recommends_rollback_request(tmp_path) -> None:
    _, application, runtime = _fixture(tmp_path)
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    payload = _assessment(application, runtime)
    payload["maximum_mae_delta_cases"] = "-3"
    value = client.post("/api/pilot-evaluation-gates", json=payload).json()
    assert value["report"]["status"] == "BLOCKED"
    assert value["report"]["recommended_action"] == "REQUEST_ROLLBACK"
