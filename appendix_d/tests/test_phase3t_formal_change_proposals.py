"""Formal change proposals require an immutable source and independent approval."""

import base64
import csv
import io
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from forecast_provider.field_learning import (
    FormalChangeTarget,
    LearningExperimentDecision,
    SqliteFieldLearningStore,
    build_experiment_decision_event,
    build_formal_change_proposal,
)
from portable.api.app import create_app
from portable.api.formal_changes import PortableFormalChanges
from portable.api.learning_experiments import PortableLearningExperiments
from portable.api.production_handoff import ProductionHandoffError
from tests.test_phase3t_learning_experiments import _approved_candidate

NOW = datetime(2026, 10, 3, 20, tzinfo=UTC)


def _recommended_run(database):
    store = SqliteFieldLearningStore(database)
    candidate, cases = _approved_candidate(store)
    experiment = PortableLearningExperiments(database)
    plan = experiment.create_plan({
        "candidate_id": candidate.candidate_id,
        "target": "DEMAND_FORECAST",
        "baseline_version": "forecast-v1",
        "challenger_version": "calendar-v2",
        "hypothesis": "販促特徴で誤差を減らす",
        "subject": "analyst",
        "known_at": NOW.isoformat(),
        "confirm_shadow_experiment": True,
    })
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output, fieldnames=("case_id", "challenger_quantity"), lineterminator="\r\n"
    )
    writer.writeheader()
    writer.writerow({"case_id": cases[0].case_id, "challenger_quantity": "12"})
    writer.writerow({"case_id": cases[1].case_id, "challenger_quantity": "7"})
    writer.writerow({"case_id": cases[2].case_id, "challenger_quantity": ""})
    view = experiment.create_run(plan["plan_id"], {
        "result_version": "comparison-v1",
        "subject": "analyst",
        "known_at": NOW.isoformat(),
        "csv_base64": base64.b64encode(output.getvalue().encode("utf-8-sig")).decode(),
        "confirm_same_case_set": True,
    })
    run = view["runs"][0]
    view = experiment.decide(run["run_id"], {
        "expected_revision": 0,
        "decision": "RECOMMEND_FORMAL_CHANGE",
        "subject": "experiment-manager",
        "reason": "共通対象で改善したため変更案を作る",
        "confirm_no_automatic_application": True,
    })
    return store, view["runs"][0]


def _proposal_payload(run_id):
    return {
        "run_id": run_id,
        "change_target": "FORECAST_FEATURE",
        "current_configuration": {"features": ["weekday"], "version": "forecast-v1"},
        "proposed_configuration": {
            "features": ["weekday", "promotion"], "version": "calendar-v2"
        },
        "application_scope": {"pilot_scope_versions": ["scope-v1"]},
        "acceptance_criteria": ["MAEがBaseline以下", "欠品実績を悪化させない"],
        "rollback_conditions": ["MAEがBaselineを超える", "データ契約違反を検出"],
        "rollback_target_version": "forecast-v1",
        "author": "proposal-author",
        "known_at": datetime.now(UTC).isoformat(),
        "confirm_no_automatic_application": True,
    }


def test_proposal_contract_requires_difference_acceptance_and_rollback() -> None:
    with pytest.raises(ValueError, match="差分"):
        build_formal_change_proposal(
            run_id="run-1", source_decision_revision=1,
            change_target=FormalChangeTarget.FORECAST_FEATURE,
            current_configuration={"version": "v1"},
            proposed_configuration={"version": "v1"},
            application_scope={"scope": "pilot"},
            acceptance_criteria=("MAEを確認",), rollback_conditions=("悪化時",),
            rollback_target_version="v1", author="author",
            known_at=NOW, recorded_at=NOW,
        )


def test_proposal_and_independent_decision_are_idempotent_and_not_applied(tmp_path) -> None:
    database = tmp_path / "field.sqlite3"
    _, run = _recommended_run(database)
    service = PortableFormalChanges(database)
    payload = _proposal_payload(run["run_id"])

    proposal = service.create_proposal(payload)
    assert service.create_proposal(payload)["proposal_id"] == proposal["proposal_id"]
    assert proposal["application_status"] == "NOT_APPLIED"
    assert proposal["status"] == "PENDING"

    decision = {
        "expected_revision": 0,
        "decision": "APPROVED_FOR_IMPLEMENTATION",
        "approver": "independent-approver",
        "reason": "差分、適用範囲、受入基準、rollback条件を確認した",
        "confirm_separate_approval": True,
    }
    approved = service.decide(proposal["proposal_id"], decision)
    repeated = service.decide(proposal["proposal_id"], decision)
    assert repeated == approved
    assert approved["status"] == "APPROVED_FOR_IMPLEMENTATION"
    assert approved["application_status"] == "NOT_APPLIED"
    assert approved["revision"] == 1


def test_author_cannot_approve_and_stale_source_decision_blocks_approval(tmp_path) -> None:
    database = tmp_path / "field.sqlite3"
    store, run = _recommended_run(database)
    service = PortableFormalChanges(database)
    proposal = service.create_proposal(_proposal_payload(run["run_id"]))

    with pytest.raises(ProductionHandoffError, match="別の担当者"):
        service.decide(proposal["proposal_id"], {
            "expected_revision": 0, "decision": "APPROVED_FOR_IMPLEMENTATION",
            "approver": "proposal-author", "reason": "自己承認",
            "confirm_separate_approval": True,
        })

    rejected = build_experiment_decision_event(
        run_id=run["run_id"], expected_revision=1,
        decision=LearningExperimentDecision.REJECT_CHANGE,
        subject="experiment-manager", reason="再確認で見送り",
        known_at=NOW + timedelta(minutes=20), recorded_at=NOW + timedelta(minutes=20),
    )
    store.append_experiment_decision(rejected, 1)
    with pytest.raises(ProductionHandoffError, match="作成推奨"):
        service.decide(proposal["proposal_id"], {
            "expected_revision": 0, "decision": "APPROVED_FOR_IMPLEMENTATION",
            "approver": "independent-approver", "reason": "承認",
            "confirm_separate_approval": True,
        })


def test_tampered_proposal_is_rejected(tmp_path) -> None:
    database = tmp_path / "field.sqlite3"
    _, run = _recommended_run(database)
    service = PortableFormalChanges(database)
    proposal = service.create_proposal(_proposal_payload(run["run_id"]))

    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE field_formal_change_proposals "
            "SET proposed_configuration_json=? WHERE proposal_id=?",
            ('{"version":"tampered"}', proposal["proposal_id"]),
        )
    with pytest.raises(ProductionHandoffError, match="整合性"):
        service.view_proposal(proposal["proposal_id"])


def test_portable_routes_and_step_14_assets_are_available(tmp_path) -> None:
    client = TestClient(create_app(tmp_path), base_url="http://localhost")

    assert client.get("/api/formal-changes").status_code == 200
    assert client.get("/formal-changes.js").status_code == 200
    assert 'id="formal-change-form"' in client.get("/").text
