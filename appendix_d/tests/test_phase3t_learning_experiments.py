"""Approved learning candidates become immutable, human-controlled comparisons."""

import base64
import csv
import io
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from forecast_provider.field_learning import (
    FieldLearningConflict,
    FieldMode,
    LearningCandidateDecision,
    LearningCandidateType,
    LearningExperimentDecision,
    LearningExperimentTarget,
    SqliteFieldLearningStore,
    build_actual_outcome_event,
    build_experiment_decision_event,
    build_experiment_plan,
    build_learning_candidate,
    build_learning_candidate_decision_event,
    build_reference_case,
    build_weekly_review,
)
from forecast_provider.field_learning.experiment import build_experiment_report
from portable.api.app import create_app
from portable.api.learning_experiments import PortableLearningExperiments

NOW = datetime(2026, 10, 3, 20, tzinfo=UTC)


def _jan(index: int) -> str:
    body = f"49012345{index:04d}"
    weighted = sum(
        int(digit) * (3 if offset % 2 == 0 else 1)
        for offset, digit in enumerate(reversed(body))
    )
    return body + str((10 - weighted % 10) % 10)


def _approved_candidate(store):
    cases = []
    for index, actual_demand in enumerate(("12", "8", None)):
        case = build_reference_case(
            business_date=date(2026, 10, 1 + index), jan=_jan(index),
            canonical_product_id=f"product-{index}", warehouse_id="warehouse-east",
            forecast_center_id="center-east", forecast_run_id="forecast-run-v1",
            inventory_snapshot_id="snapshot-v1", pilot_scope_version="scope-v1",
            identity_bridge_version="bridge-v1", system_forecast_quantity="10",
            system_reference_quantity="5", policy_version="policy-v1",
            mode=FieldMode.SHADOW, known_at=NOW - timedelta(days=7),
            recorded_at=NOW - timedelta(days=7),
        )
        store.put_reference_case(case)
        cases.append(case)
        if actual_demand is not None:
            actual = build_actual_outcome_event(
                case_id=case.case_id, expected_revision=0, source_version="actual-v1",
                source_sha256=str(index + 1) * 64, actual_shipped_quantity="5",
                actual_demand_quantity=actual_demand, stockout_quantity="0",
                expired_quantity=None, interwarehouse_transfer_quantity="0",
                known_at=NOW - timedelta(hours=2), recorded_at=NOW - timedelta(hours=1),
            )
            store.append_actual_outcome(actual, 0)
    review = build_weekly_review(
        week_start=date(2026, 9, 28), week_end=date(2026, 10, 4),
        pilot_scope_versions=("scope-v1",), aggregation_version="weekly-v1",
        threshold_version="threshold-v1", report={"current": {}}, reviewer="manager",
        known_at=NOW - timedelta(minutes=30), recorded_at=NOW - timedelta(minutes=20),
    )
    candidate = build_learning_candidate(
        review_id=review.review_id, candidate_type=LearningCandidateType.CALENDAR_FEATURE,
        evidence_count=3, impact_quantity="4", reason_codes=("PROMOTION",),
        evidence_case_ids=tuple(case.case_id for case in cases),
    )
    store.put_weekly_review(review, (candidate,))
    approved = build_learning_candidate_decision_event(
        candidate_id=candidate.candidate_id, expected_revision=0,
        decision=LearningCandidateDecision.APPROVED, subject="manager",
        reason="販促特徴を比較する", known_at=NOW - timedelta(minutes=10),
        recorded_at=NOW - timedelta(minutes=5),
    )
    store.append_learning_candidate_decision(approved, 0)
    return candidate, cases


def test_common_case_comparison_preserves_missing_and_observed_outcomes(tmp_path) -> None:
    store = SqliteFieldLearningStore(tmp_path / "field.sqlite3")
    candidate, cases = _approved_candidate(store)
    plan = build_experiment_plan(
        candidate_id=candidate.candidate_id, target=LearningExperimentTarget.DEMAND_FORECAST,
        baseline_version="forecast-v1", challenger_version="calendar-v2",
        hypothesis="販促特徴で誤差を減らす", evidence_case_ids=candidate.evidence_case_ids,
        subject="analyst", known_at=NOW, recorded_at=NOW,
    )
    report = build_experiment_report(
        store, plan, {cases[0].case_id: 12, cases[1].case_id: 7}, known_at=NOW,
    )

    assert report["coverage"]["planned_count"] == 3
    assert report["coverage"]["comparable_count"] == 2
    assert report["coverage"]["missing_challenger_case_ids"] == [cases[2].case_id]
    assert report["coverage"]["missing_actual_case_ids"] == [cases[2].case_id]
    assert report["baseline"]["mae_cases"] == "2"
    assert report["challenger"]["mae_cases"] == "0.5"
    assert report["delta_challenger_minus_baseline"]["mae_cases"] == "-1.5"
    assert report["quantity_gap_proxies"]["delta_challenger_minus_baseline"] == {
        "under_supply_cases": "-1",
        "excess_supply_cases": "-2",
    }
    assert report["comparison"]["challenger_better_count"] == 2
    assert report["observed_business_outcomes"]["stockout_cases"] == "0"
    assert report["observed_business_outcomes"]["expired_cases"] is None


def test_portable_plan_run_and_decision_are_idempotent_and_append_only(tmp_path) -> None:
    database = tmp_path / "field.sqlite3"
    store = SqliteFieldLearningStore(database)
    candidate, cases = _approved_candidate(store)
    service = PortableLearningExperiments(database)
    plan_payload = {
        "candidate_id": candidate.candidate_id,
        "target": "DEMAND_FORECAST",
        "baseline_version": "forecast-v1",
        "challenger_version": "calendar-v2",
        "hypothesis": "販促特徴で誤差を減らす",
        "subject": "analyst",
        "known_at": NOW.isoformat(),
        "confirm_shadow_experiment": True,
    }
    plan = service.create_plan(plan_payload)
    assert service.create_plan(plan_payload)["plan_id"] == plan["plan_id"]
    assert service.template(plan["plan_id"]).startswith(b"\xef\xbb\xbfcase_id")

    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output, fieldnames=("case_id", "challenger_quantity"), lineterminator="\r\n"
    )
    writer.writeheader()
    writer.writerow({"case_id": cases[0].case_id, "challenger_quantity": "12"})
    writer.writerow({"case_id": cases[1].case_id, "challenger_quantity": "7"})
    writer.writerow({"case_id": cases[2].case_id, "challenger_quantity": ""})
    run_payload = {
        "result_version": "comparison-v1",
        "subject": "analyst",
        "known_at": NOW.isoformat(),
        "csv_base64": base64.b64encode(output.getvalue().encode("utf-8-sig")).decode(),
        "confirm_same_case_set": True,
    }
    after_run = service.create_run(plan["plan_id"], run_payload)
    repeated = service.create_run(plan["plan_id"], run_payload)
    assert repeated["runs"][0]["run_id"] == after_run["runs"][0]["run_id"]
    run = after_run["runs"][0]
    decided = service.decide(run["run_id"], {
        "expected_revision": 0,
        "decision": "RECOMMEND_FORMAL_CHANGE",
        "subject": "manager",
        "reason": "共通対象でMAEが改善したため正式変更案を作る",
        "confirm_no_automatic_application": True,
    })
    assert decided["runs"][0]["status"] == "RECOMMEND_FORMAL_CHANGE"
    same = service.decide(run["run_id"], {
        "expected_revision": 0,
        "decision": "RECOMMEND_FORMAL_CHANGE",
        "subject": "manager",
        "reason": "共通対象でMAEが改善したため正式変更案を作る",
        "confirm_no_automatic_application": True,
    })
    assert same == decided

    conflicting = build_experiment_decision_event(
        run_id=run["run_id"], expected_revision=0,
        decision=LearningExperimentDecision.REJECT_CHANGE,
        subject="manager", reason="競合", known_at=NOW, recorded_at=NOW,
    )
    with pytest.raises(FieldLearningConflict, match="先に"):
        store.append_experiment_decision(conflicting, 0)


def test_plan_requires_approved_candidate(tmp_path) -> None:
    store = SqliteFieldLearningStore(tmp_path / "field.sqlite3")
    candidate, _ = _approved_candidate(store)
    rejected = build_learning_candidate_decision_event(
        candidate_id=candidate.candidate_id, expected_revision=1,
        decision=LearningCandidateDecision.REJECTED, subject="manager",
        reason="今回は見送る", known_at=NOW, recorded_at=NOW,
    )
    store.append_learning_candidate_decision(rejected, 1)
    service = PortableLearningExperiments(store.path)
    with pytest.raises(ValueError, match="APPROVED"):
        service.create_plan({
            "candidate_id": candidate.candidate_id, "target": "DEMAND_FORECAST",
            "baseline_version": "v1", "challenger_version": "v2",
            "hypothesis": "test", "subject": "analyst", "known_at": NOW.isoformat(),
            "confirm_shadow_experiment": True,
        })


def test_portable_routes_and_step_13_assets_are_available(tmp_path) -> None:
    client = TestClient(create_app(tmp_path), base_url="http://localhost")

    assert client.get("/api/learning-experiments").status_code == 200
    assert client.get("/learning-experiments.js").status_code == 200
    assert 'id="experiment-plan-form"' in client.get("/").text
