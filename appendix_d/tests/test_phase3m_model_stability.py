"""Phase 3M: 複数条件におけるモデル順位・精度の安定性集計。"""

import pytest

from forecast_provider.api.campaign_results import summarize_model_stability


def _model(
    provider_id: str,
    model_id: str,
    rank: int | None,
    wape: float | None,
    bias: float | None,
    success: float | None,
    *,
    eligible: bool = True,
) -> dict:
    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "rank": rank,
        "wape_pct": wape,
        "bias_rate_pct": bias,
        "success_rate_pct": success,
        "official_eligible": eligible,
    }


def test_stability_summarizes_coverage_rank_accuracy_and_bias() -> None:
    tests = [
        {
            "models": [
                _model("p", "a", 1, 10, -2, 100),
                _model("p", "b", 2, 12, 1, 99),
            ]
        },
        {
            "models": [
                _model("p", "a", 2, 30, 4, 90),
                _model("p", "b", 1, 20, -3, 100),
            ]
        },
        {
            "models": [
                _model("p", "a", None, None, None, 80, eligible=False),
                _model("p", "b", 1, 18, 0, 100),
            ]
        },
    ]

    result = summarize_model_stability(tests)
    values = {item["model_id"]: item for item in result["models"]}

    assert result["completed_test_count"] == 3
    assert [item["model_id"] for item in result["models"]] == ["b", "a"]
    assert values["a"] == {
        "provider_id": "p",
        "model_id": "a",
        "completed_test_count": 3,
        "configured_test_count": 3,
        "eligible_test_count": 2,
        "official_coverage_pct": pytest.approx(200 / 3),
        "overall_coverage_pct": pytest.approx(200 / 3),
        "win_count": 1,
        "win_rate_pct": 50,
        "mean_rank": 1.5,
        "rank_stddev": 0.5,
        "rank_min": 1,
        "rank_max": 2,
        "rank_range": 1,
        "varies_by_condition": True,
        "wape_mean_pct": 20,
        "wape_min_pct": 10,
        "wape_max_pct": 30,
        "wape_stddev_pct": 10,
        "wape_range_pct": 20,
        "mean_abs_bias_rate_pct": 3,
        "min_success_rate_pct": 90,
    }
    assert values["b"]["official_coverage_pct"] == 100
    assert values["b"]["win_count"] == 2
    assert values["b"]["win_rate_pct"] == pytest.approx(200 / 3)
    assert values["b"]["mean_rank"] == pytest.approx(4 / 3)
    assert values["b"]["wape_mean_pct"] == pytest.approx(50 / 3)
    assert values["b"]["wape_range_pct"] == 8
    assert values["b"]["mean_abs_bias_rate_pct"] == pytest.approx(4 / 3)
    assert values["b"]["min_success_rate_pct"] == 99


def test_stability_handles_empty_and_single_test_without_claiming_variation() -> None:
    assert summarize_model_stability([]) == {
        "completed_test_count": 0,
        "models": [],
    }

    result = summarize_model_stability(
        [{"models": [_model("provider", "model", 1, 8, None, None)]}]
    )["models"][0]

    assert result["rank_stddev"] == 0
    assert result["wape_stddev_pct"] == 0
    assert result["varies_by_condition"] is False
    assert result["mean_abs_bias_rate_pct"] is None
    assert result["min_success_rate_pct"] is None

