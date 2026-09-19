"""Phase 3N: 同一条件の公式比較結果に対する時系列変化集計。"""

from forecast_provider.api.campaign_drift import (
    dataset_profile,
    model_profile,
    summarize_model_drift,
)


def _model(model_id: str, wape: float, bias: float, success: float, rank: int) -> dict:
    return {
        "provider_id": "provider",
        "model_id": model_id,
        "model_profile_hash": f"profile-{model_id}",
        "official_eligible": True,
        "wape_pct": wape,
        "bias_rate_pct": bias,
        "success_rate_pct": success,
        "rank": rank,
    }


def _test(
    campaign_id: str,
    selection_version: str,
    test_start: str,
    test_end: str,
    models: list[dict],
    *,
    population_hash: str = "same-population",
    primary_horizon_max: int = 7,
    created_at: str = "2026-09-19T00:00:00+00:00",
) -> dict:
    return {
        "campaign_id": campaign_id,
        "selection_version": selection_version,
        "test_start": test_start,
        "test_end": test_end,
        "created_at": created_at,
        "population_hash": population_hash,
        "known_future_hash": "same-known-future",
        "population_size": 3,
        "train_days": 365,
        "test_days": 30,
        "availability_mode": "OBSERVED",
        "mode": "primary",
        "horizon": None,
        "origin_interval_days": 7,
        "max_horizon": 7,
        "primary_horizon_max": primary_horizon_max,
        "models": models,
    }


def test_drift_compares_only_matching_profiles_and_reports_metric_changes() -> None:
    first = _test(
        "campaign-1",
        "selection-v1",
        "2026-07-01",
        "2026-07-30",
        [
            _model("up", 10, -2, 100, 1),
            _model("down", 20, 4, 90, 3),
            _model("same", 15, 1, 95, 2),
        ],
    )
    second = _test(
        "campaign-2",
        "selection-v2",
        "2026-08-01",
        "2026-08-30",
        [
            _model("up", 12, 3, 98, 2),
            _model("down", 15, -2, 100, 1),
            _model("same", 15, -1, 95, 2),
        ],
    )
    other_population = _test(
        "campaign-other",
        "selection-v3",
        "2026-08-01",
        "2026-08-30",
        [_model("up", 99, 30, 10, 1)],
        population_hash="other-population",
    )
    other_horizon = _test(
        "campaign-h14",
        "selection-v4",
        "2026-08-01",
        "2026-08-30",
        [_model("up", 50, 10, 100, 1)],
        primary_horizon_max=14,
    )

    result = summarize_model_drift([first, second, other_population, other_horizon])
    values = {
        (item["model_id"], item["history_count"]): item for item in result["series"]
    }

    assert result["series_count"] == 5
    assert result["comparable_series_count"] == 3
    up = values[("up", 2)]
    assert up["direction"] == "WAPE_UP"
    assert up["wape_change_pct_points"] == 2
    assert up["wape_relative_change_pct"] == 20
    assert up["abs_bias_change_pct_points"] == 1
    assert up["success_rate_change_pct_points"] == -2
    assert up["rank_change"] == 1
    assert up["period_gap_days"] == 1
    assert up["previous"]["selection_version"] == "selection-v1"
    assert up["latest"]["selection_version"] == "selection-v2"
    assert values[("down", 2)]["direction"] == "WAPE_DOWN"
    assert values[("same", 2)]["direction"] == "UNCHANGED"
    one_period_up = [
        item
        for item in result["series"]
        if item["model_id"] == "up" and item["history_count"] == 1
    ]
    assert len(one_period_up) == 2
    assert all(item["direction"] == "INSUFFICIENT_HISTORY" for item in one_period_up)


def test_drift_deduplicates_same_period_and_excludes_ineligible_results() -> None:
    old = _test(
        "campaign-old",
        "selection-v1",
        "2026-07-01",
        "2026-07-30",
        [_model("model", 10, 1, 100, 1)],
        created_at="2026-09-18T00:00:00+00:00",
    )
    replacement = _test(
        "campaign-new",
        "selection-v1b",
        "2026-07-01",
        "2026-07-30",
        [_model("model", 11, 1, 100, 1)],
        created_at="2026-09-19T00:00:00+00:00",
    )
    excluded = _model("excluded", 9, 0, 100, 1)
    excluded["official_eligible"] = False
    replacement["models"].append(excluded)

    result = summarize_model_drift([old, replacement])

    assert result["series_count"] == 1
    assert result["comparable_series_count"] == 0
    assert result["series"][0]["history_count"] == 1
    assert result["series"][0]["latest"]["campaign_id"] == "campaign-new"


def test_dataset_and_model_profiles_ignore_order_and_snapshot_identity() -> None:
    manifest = {
        "unique_ids": ["b", "a"],
        "known_future_columns": ["holiday", "promotion"],
        "train_start": "2025-01-01",
        "train_end": "2025-12-31",
        "test_start": "2026-01-01",
        "test_end": "2026-01-30",
        "availability_mode": "OBSERVED",
    }
    reordered = {
        **manifest,
        "unique_ids": ["a", "b"],
        "known_future_columns": ["promotion", "holiday"],
    }

    assert dataset_profile(manifest) == dataset_profile(reordered)
    assert dataset_profile(manifest)["train_days"] == 365
    assert dataset_profile(manifest)["test_days"] == 30
    assert model_profile({"snapshot_id": "one", "model_name": "m", "seed": 7}) == model_profile(
        {"snapshot_id": "two", "model_name": "m", "seed": 7}
    )
    assert model_profile({"snapshot_id": "one", "model_name": "m", "seed": 7}) != model_profile(
        {"snapshot_id": "one", "model_name": "m", "seed": 8}
    )


def test_relative_wape_change_is_unknown_when_previous_wape_is_zero() -> None:
    first = _test(
        "campaign-1", "v1", "2026-07-01", "2026-07-30", [_model("m", 0, 0, 100, 1)]
    )
    second = _test(
        "campaign-2", "v2", "2026-08-01", "2026-08-30", [_model("m", 1, 0, 100, 1)]
    )

    series = summarize_model_drift([first, second])["series"][0]

    assert series["wape_change_pct_points"] == 1
    assert series["wape_relative_change_pct"] is None
    assert series["direction"] == "WAPE_UP"
