"""Approved formal changes pass an audited Pilot gate before acceptance."""

import sqlite3
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from forecast_provider.field_learning import (
    ChangeApplicationState,
    ChangeApplicationTransition,
    build_change_application,
    build_change_application_event,
)
from portable.api.app import create_app
from portable.api.change_applications import PortableChangeApplications
from portable.api.formal_changes import PortableFormalChanges
from portable.api.production_handoff import ProductionHandoffError
from tests.test_phase3t_formal_change_proposals import _proposal_payload, _recommended_run

NOW = datetime(2026, 10, 4, 1, tzinfo=UTC)


def _approved_proposal(database):
    _, run = _recommended_run(database)
    formal = PortableFormalChanges(database)
    proposal = formal.create_proposal(_proposal_payload(run["run_id"]))
    proposal = formal.decide(proposal["proposal_id"], {
        "expected_revision": 0,
        "decision": "APPROVED_FOR_IMPLEMENTATION",
        "approver": "independent-approver",
        "reason": "Pilot実装案として承認する",
        "confirm_separate_approval": True,
    })
    return formal, proposal


def _application_payload(proposal_id):
    return {
        "proposal_id": proposal_id,
        "candidate_version": "calendar-v2-pilot.1",
        "backup_reference": "backup-20261004-001",
        "backup_sha256": "a" * 64,
        "executor": "pilot-operator",
        "known_at": datetime.now(UTC).isoformat(),
        "confirm_pilot_only": True,
    }


def _checks(passed=True):
    return [
        {"name": "API起動", "passed": passed, "evidence": "ready応答を確認"},
        {"name": "Pilot参照", "passed": passed, "evidence": "対象範囲を確認"},
    ]


def _transition_payload(revision, **extra):
    return {
        "expected_revision": revision,
        "actor": "pilot-operator",
        "reason": "試験結果を記録する",
        "confirm_audited_transition": True,
        **extra,
    }


def _active_application(database):
    _, proposal = _approved_proposal(database)
    service = PortableChangeApplications(database)
    application = service.create_application(_application_payload(proposal["proposal_id"]))
    application = service.evaluate_gate(application["application_id"], _transition_payload(
        0, backup_verified=True, candidate_staged=True, smoke_checks=_checks(),
    ))
    return service, application


def test_application_domain_requires_backup_sha_and_hashes_events() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        build_change_application(
            proposal_id="proposal-1", source_proposal_decision_revision=1,
            candidate_version="candidate-v1", application_scope={"scope": "pilot"},
            backup_reference="backup-1", backup_sha256="bad", executor="operator",
            known_at=NOW, recorded_at=NOW,
        )
    event = build_change_application_event(
        application_id="application-1", expected_revision=0,
        transition=ChangeApplicationTransition.PILOT_GATE_EVALUATED,
        resulting_state=ChangeApplicationState.PILOT_ACTIVE,
        actor="operator", reason="検査合格", evidence={"smoke": "PASS"},
        known_at=NOW, recorded_at=NOW,
    )
    assert event.revision == 1
    assert len(event.content_sha256) == 64


def test_approved_change_reaches_accepted_without_mutating_formal_proposal(tmp_path) -> None:
    database = tmp_path / "field.sqlite3"
    service, application = _active_application(database)
    assert application["state"] == "PILOT_ACTIVE"
    assert application["revision"] == 1

    application = service.evaluate_acceptance(
        application["application_id"],
        _transition_payload(
            1,
            acceptance_results=[
                {"statement": item, "passed": True, "evidence": "Pilot期間で合格"}
                for item in application["proposal"]["acceptance_criteria"]
            ],
            rollback_results=[
                {"statement": item, "triggered": False, "evidence": "該当なし"}
                for item in application["proposal"]["rollback_conditions"]
            ],
        ),
    )
    assert application["state"] == "ACCEPTED"
    assert application["next_action"] == "COMPLETE"
    overview = service.overview()
    assert overview["active_assignments"][0]["state"] == "ACCEPTED"

    with sqlite3.connect(database) as db:
        value = db.execute(
            "SELECT application_status FROM field_formal_change_proposals"
        ).fetchone()[0]
    assert value == "NOT_APPLIED"


def test_failed_gate_is_blocked_and_can_be_retried(tmp_path) -> None:
    database = tmp_path / "field.sqlite3"
    _, proposal = _approved_proposal(database)
    service = PortableChangeApplications(database)
    application = service.create_application(_application_payload(proposal["proposal_id"]))
    application = service.evaluate_gate(application["application_id"], _transition_payload(
        0, backup_verified=True, candidate_staged=True, smoke_checks=_checks(False),
    ))
    assert application["state"] == "BLOCKED"
    assert application["next_action"] == "FIX_AND_RETRY_PILOT_GATE"

    application = service.evaluate_gate(application["application_id"], _transition_payload(
        1, backup_verified=True, candidate_staged=True, smoke_checks=_checks(True),
    ))
    assert application["state"] == "PILOT_ACTIVE"
    assert application["revision"] == 2


def test_acceptance_failure_requires_verified_rollback(tmp_path) -> None:
    database = tmp_path / "field.sqlite3"
    service, application = _active_application(database)
    acceptance = [
        {"statement": item, "passed": index != 0, "evidence": "評価結果"}
        for index, item in enumerate(application["proposal"]["acceptance_criteria"])
    ]
    rollback = [
        {"statement": item, "triggered": index == 0, "evidence": "条件評価"}
        for index, item in enumerate(application["proposal"]["rollback_conditions"])
    ]
    application = service.evaluate_acceptance(
        application["application_id"],
        _transition_payload(
            1, acceptance_results=acceptance, rollback_results=rollback,
        ),
    )
    assert application["state"] == "ROLLBACK_REQUIRED"

    application = service.evaluate_rollback(
        application["application_id"],
        _transition_payload(
            2, rollback_target_version="forecast-v1", backup_restored=False,
            rollback_checks=_checks(False),
        ),
    )
    assert application["state"] == "ROLLBACK_REQUIRED"
    application = service.evaluate_rollback(
        application["application_id"],
        _transition_payload(
            3, rollback_target_version="forecast-v1", backup_restored=True,
            rollback_checks=_checks(True),
        ),
    )
    assert application["state"] == "ROLLED_BACK"
    assert application["next_action"] == "COMPLETE"


def test_newer_rejection_blocks_application_transition(tmp_path) -> None:
    database = tmp_path / "field.sqlite3"
    formal, proposal = _approved_proposal(database)
    service = PortableChangeApplications(database)
    application = service.create_application(_application_payload(proposal["proposal_id"]))
    formal.decide(proposal["proposal_id"], {
        "expected_revision": 1,
        "decision": "REJECTED",
        "approver": "independent-approver",
        "reason": "新しい情報により承認を撤回する",
        "confirm_separate_approval": True,
    })
    with pytest.raises(ProductionHandoffError, match="承認済み"):
        service.evaluate_gate(application["application_id"], _transition_payload(
            0, backup_verified=True, candidate_staged=True, smoke_checks=_checks(),
        ))


def test_tampered_application_and_assets_are_detected(tmp_path) -> None:
    database = tmp_path / "field.sqlite3"
    _, proposal = _approved_proposal(database)
    service = PortableChangeApplications(database)
    application = service.create_application(_application_payload(proposal["proposal_id"]))
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE field_change_applications SET candidate_version=? WHERE application_id=?",
            ("tampered", application["application_id"]),
        )
    with pytest.raises(ProductionHandoffError, match="整合性"):
        service.view_application(application["application_id"])

    client = TestClient(create_app(tmp_path / "ui"), base_url="http://localhost")
    assert client.get("/api/change-applications").status_code == 200
    assert client.get("/change-applications.js").status_code == 200
    assert 'id="change-application-form"' in client.get("/").text
