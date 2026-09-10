"""重要品目候補jobと確定選定版の入力契約。"""

import pytest

from forecast_provider.selection import make_candidate_job, make_selection


def candidate_payload():
    return {
        "candidate_version": "candidate-v1",
        "daily_build_id": "daily-1",
        "business_product_ids": ["P2", "P1"],
        "max_missing_rate": 0.1,
        "stable_cv_max": 0.25,
        "intermittent_zero_rate_min": 0.5,
        "requested_by": "operator@example.test",
        "purpose": "重要品目候補の確認",
    }


def selection_payload(count=3, scope="INITIAL"):
    return {
        "selection_version": "selection-v1",
        "candidate_job_id": "candidate-job-1",
        "scope": scope,
        "items": [
            {
                "canonical_product_id": f"P{index:02}",
                "center_ids": ["C2", "C1"],
                "reason": f"選定理由{index}",
            }
            for index in range(count)
        ],
        "selected_by": "operator@example.test",
        "rationale": "数量・変動・欠損と業務優先度を確認",
    }


def test_candidate_job_is_content_addressed_and_normalized():
    first = make_candidate_job(candidate_payload())
    reordered = candidate_payload()
    reordered["business_product_ids"] = ["P1", "P2"]
    second = make_candidate_job(reordered)
    assert first.candidate_job_id == second.candidate_job_id
    assert first.definition["business_product_ids"] == ["P1", "P2"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_missing_rate", 1.1),
        ("stable_cv_max", -0.1),
        ("intermittent_zero_rate_min", -0.1),
    ],
)
def test_candidate_thresholds_are_validated(field, value):
    payload = candidate_payload()
    payload[field] = value
    with pytest.raises(ValueError):
        make_candidate_job(payload)


def test_initial_and_full_selection_sizes_are_enforced():
    assert make_selection(selection_payload()).definition["scope"] == "INITIAL"
    assert len(make_selection(selection_payload(20, "FULL")).definition["items"]) == 20
    with pytest.raises(ValueError, match="3〜5"):
        make_selection(selection_payload(2))
    with pytest.raises(ValueError, match="20〜50"):
        make_selection(selection_payload(19, "FULL"))


def test_selection_items_are_unique_and_have_centers_and_reasons():
    payload = selection_payload()
    payload["items"][1]["canonical_product_id"] = payload["items"][0][
        "canonical_product_id"
    ]
    with pytest.raises(ValueError, match="重複"):
        make_selection(payload)
    payload = selection_payload()
    payload["items"][0]["center_ids"] = []
    with pytest.raises(ValueError, match="center_ids"):
        make_selection(payload)
    payload = selection_payload()
    payload["items"][0]["reason"] = ""
    with pytest.raises(ValueError, match="reason"):
        make_selection(payload)
