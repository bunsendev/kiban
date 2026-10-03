"""Weekly SHADOW review snapshots and explicit learning-candidate decisions."""

from datetime import UTC, date, datetime, timedelta

import pytest

from forecast_provider.field_learning import (
    FieldLearningConflict,
    FieldMode,
    LearningCandidateDecision,
    OperatorDecision,
    OperatorReasonCode,
    SqliteFieldLearningStore,
    build_actual_outcome_event,
    build_learning_candidate_decision_event,
    build_operator_decision_event,
    build_reference_case,
)
from forecast_provider.field_learning.weekly import build_weekly_review_bundle

NOW = datetime(2026, 10, 4, 3, tzinfo=UTC)


def _jan(index: int) -> str:
    body = f"49012345{index:04d}"
    weighted = sum(
        int(digit) * (3 if offset % 2 == 0 else 1)
        for offset, digit in enumerate(reversed(body))
    )
    return body + str((10 - weighted % 10) % 10)


def _case(store, index: int, business_date: date):
    case = build_reference_case(
        business_date=business_date,
        jan=_jan(index),
        canonical_product_id=f"product-{index}",
        warehouse_id="warehouse-east",
        forecast_center_id="center-east",
        forecast_run_id="forecast-run-1",
        inventory_snapshot_id="snapshot-1",
        pilot_scope_version="scope-v1",
        identity_bridge_version="bridge-v1",
        system_forecast_quantity="10",
        system_reference_quantity="5",
        policy_version="policy-v1",
        mode=FieldMode.SHADOW,
        known_at=NOW - timedelta(days=7),
        recorded_at=NOW - timedelta(days=7),
    )
    store.put_reference_case(case)
    return case


def test_weekly_review_preserves_missing_and_candidate_approval_history(tmp_path) -> None:
    store = SqliteFieldLearningStore(tmp_path / "field.sqlite3")
    cases = [_case(store, index, date(2026, 10, 1 + index)) for index in range(4)]
    for case in cases[:2]:
        decision = build_operator_decision_event(
            case=case,
            expected_revision=0,
            operator_decision=OperatorDecision.INCREASED,
            operator_quantity="8",
            operator_reason_code=OperatorReasonCode.EXPECTED_LARGE_ORDER,
            operator_comment=None,
            subject="operator",
            known_at=NOW - timedelta(hours=2),
            recorded_at=NOW - timedelta(hours=1),
        )
        store.append_operator_decision(decision, 0)
    for index, case in enumerate(cases[:2]):
        actual = build_actual_outcome_event(
            case_id=case.case_id,
            expected_revision=0,
            source_version="actual-v1",
            source_sha256=chr(ord("a") + index) * 64,
            actual_shipped_quantity="8",
            actual_demand_quantity=str(12 + index),
            stockout_quantity="0",
            expired_quantity=None,
            interwarehouse_transfer_quantity="0",
            known_at=NOW - timedelta(minutes=30),
            recorded_at=NOW - timedelta(minutes=20),
        )
        store.append_actual_outcome(actual, 0)

    review, candidates = build_weekly_review_bundle(
        store,
        week_end=date(2026, 10, 4),
        pilot_scope_versions=("scope-v1",),
        aggregation_version="weekly-v1",
        threshold_version="threshold-v1",
        minimum_evidence_count=2,
        reviewer="reviewer",
        known_at=NOW,
        recorded_at=NOW,
    )
    store.put_weekly_review(review, candidates)

    assert review.report["current"]["comparison_coverage"] == {
        "system_operator": 2,
        "forecast_actual_demand": 2,
        "operator_actual_shipped": 2,
        "actual_any": 2,
        "actual_missing": 2,
    }
    assert review.report["current"]["operational_kpis"]["expired_cases"] is None
    assert {item.candidate_type.value for item in candidates} == {
        "LARGE_ORDER_INPUT",
        "DATA_QUALITY",
    }
    assert store.put_weekly_review(review, candidates) == review

    candidate = next(
        item for item in candidates if item.candidate_type.value == "LARGE_ORDER_INPUT"
    )
    event = build_learning_candidate_decision_event(
        candidate_id=candidate.candidate_id,
        expected_revision=0,
        decision=LearningCandidateDecision.APPROVED,
        subject="manager",
        reason="大口予定の取得方法を調査",
        known_at=NOW,
        recorded_at=NOW,
    )
    store.append_learning_candidate_decision(event, 0)
    assert store.list_learning_candidate_decisions(candidate.candidate_id) == [event]
    with pytest.raises(FieldLearningConflict, match="先に"):
        store.append_learning_candidate_decision(event, 0)


def test_weekly_review_uses_known_at_cutoff_and_rejects_empty_scope(tmp_path) -> None:
    store = SqliteFieldLearningStore(tmp_path / "field.sqlite3")
    case = _case(store, 0, date(2026, 10, 4))
    future = build_actual_outcome_event(
        case_id=case.case_id,
        expected_revision=0,
        source_version="future-v1",
        source_sha256="f" * 64,
        actual_shipped_quantity="5",
        actual_demand_quantity="10",
        stockout_quantity="0",
        expired_quantity="0",
        interwarehouse_transfer_quantity="0",
        known_at=NOW + timedelta(days=1),
        recorded_at=NOW + timedelta(days=1),
    )
    store.append_actual_outcome(future, 0)
    review, _ = build_weekly_review_bundle(
        store,
        week_end=date(2026, 10, 4),
        pilot_scope_versions=("scope-v1",),
        aggregation_version="weekly-v1",
        threshold_version="threshold-v1",
        minimum_evidence_count=1,
        reviewer="reviewer",
        known_at=NOW,
        recorded_at=NOW,
    )
    assert review.report["current"]["comparison_coverage"]["actual_any"] == 0
    assert review.report["current"]["forecast_kpis"]["mae_cases"] is None
    with pytest.raises(ValueError, match="比較対象"):
        build_weekly_review_bundle(
            store,
            week_end=date(2026, 10, 4),
            pilot_scope_versions=("missing-scope",),
            aggregation_version="weekly-v1",
            threshold_version="threshold-v1",
            minimum_evidence_count=1,
            reviewer="reviewer",
            known_at=NOW,
            recorded_at=NOW,
        )
