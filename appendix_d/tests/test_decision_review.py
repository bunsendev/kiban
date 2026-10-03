import sqlite3
from pathlib import Path

import pytest

from portable.api.decision_review import (
    DecisionReviewConflict,
    PortableDecisionReviews,
)
from portable.api.production_handoff import ProductionHandoffError


def result() -> dict:
    return {
        "request_key": "a" * 64,
        "result_sha256": "b" * 64,
        "recommendations": [
            {
                "jan": "4901234567894",
                "warehouse_id": "W01",
                "recommended_shipment_cases": "10",
            },
            {
                "jan": "4901234567894",
                "warehouse_id": "W02",
                "recommended_shipment_cases": "0",
            },
        ],
    }


def payload(**overrides) -> dict:
    values = {
        "jan": "4901234567894",
        "warehouse_id": "W01",
        "expected_revision": 0,
        "operator_decision": "ACCEPTED",
        "operator_quantity_cases": "10",
        "reason_code": None,
        "comment": None,
        "actor": "現場担当者",
        "confirm_shadow_review": True,
    }
    values.update(overrides)
    return values


def test_review_is_append_only_idempotent_and_revision_guarded(tmp_path: Path) -> None:
    service = PortableDecisionReviews(tmp_path / "reviews.sqlite3")
    first = service.record(result(), payload())
    repeated = service.record(result(), payload())
    second_payload = payload(
        expected_revision=1,
        operator_decision="INCREASED",
        operator_quantity_cases="12",
        reason_code="EXPERIENCE_JUDGMENT",
        comment="現場の得意先情報を確認",
    )
    second = service.record(result(), second_payload)

    assert repeated == first
    assert (first["revision"], second["revision"]) == (1, 2)
    view = service.view(result())
    assert len(view["history"]) == 2
    assert view["latest"]["4901234567894::W01"]["revision"] == 2
    assert view["improvement_candidates"] == [
        {
            "operator_decision": "INCREASED",
            "reason_code": "EXPERIENCE_JUDGMENT",
            "count": 1,
            "average_delta_cases": "2",
            "targets": [{"jan": "4901234567894", "warehouse_id": "W01"}],
            "automatic_application": False,
        }
    ]
    with pytest.raises(DecisionReviewConflict, match="先に"):
        service.record(result(), payload(expected_revision=1, operator_decision="REJECTED",
                                         operator_quantity_cases=None,
                                         reason_code="DATA_ERROR"))


@pytest.mark.parametrize(
    ("decision", "quantity", "reason", "message"),
    [
        ("ACCEPTED", "9", None, "一致"),
        ("INCREASED", "10", "STOCKOUT_CONCERN", "大きい"),
        ("DECREASED", "11", "EXPIRY_CONCERN", "小さい"),
        ("REJECTED", None, None, "判断理由"),
        ("INCREASED", "11", "OTHER", "補足"),
    ],
)
def test_review_validates_quantity_and_reason(
    tmp_path: Path, decision: str, quantity: str | None, reason: str | None, message: str
) -> None:
    service = PortableDecisionReviews(tmp_path / "reviews.sqlite3")
    with pytest.raises(ProductionHandoffError, match=message):
        service.record(
            result(),
            payload(
                operator_decision=decision,
                operator_quantity_cases=quantity,
                reason_code=reason,
            ),
        )


def test_rejected_and_confirmed_zero_are_not_converted_to_missing(tmp_path: Path) -> None:
    service = PortableDecisionReviews(tmp_path / "reviews.sqlite3")
    rejected = service.record(
        result(),
        payload(
            operator_decision="REJECTED",
            operator_quantity_cases=None,
            reason_code="DATA_ERROR",
        ),
    )
    no_action = service.record(
        result(),
        payload(
            warehouse_id="W02",
            operator_decision="NO_ACTION",
            operator_quantity_cases="0",
        ),
    )

    assert rejected["operator_quantity_cases"] is None
    assert no_action["operator_quantity_cases"] == "0"
    assert no_action["delta_cases"] == "0"


def test_unknown_target_and_unconfirmed_shadow_are_rejected(tmp_path: Path) -> None:
    service = PortableDecisionReviews(tmp_path / "reviews.sqlite3")
    with pytest.raises(ProductionHandoffError, match="ありません"):
        service.record(result(), payload(warehouse_id="W99"))
    with pytest.raises(ProductionHandoffError, match="SHADOW"):
        service.record(result(), payload(confirm_shadow_review=False))


def test_review_tampering_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "reviews.sqlite3"
    service = PortableDecisionReviews(database)
    service.record(result(), payload())
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE shipment_decision_reviews SET operator_quantity_cases='999'"
        )

    with pytest.raises(ProductionHandoffError, match="整合性"):
        service.view(result())
