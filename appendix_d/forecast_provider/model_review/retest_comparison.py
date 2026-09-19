"""追加テスト前後の保存済み公式結果を事実差分へ整形する。"""

from __future__ import annotations


def summarize_retest_comparison(
    source: dict,
    retest: dict,
    *,
    focus_provider_id: str | None = None,
    focus_model_id: str | None = None,
) -> dict:
    """同じモデルキーを突き合わせ、欠損を0とみなさず差分を返す。"""
    source_models = {_key(item): item for item in source["models"]}
    retest_models = {_key(item): item for item in retest["models"]}
    keys = sorted(set(source_models) | set(retest_models))
    models = [
        _model_delta(key, source_models.get(key), retest_models.get(key))
        for key in keys
    ]
    focus = next(
        (
            item
            for item in models
            if item["provider_id"] == focus_provider_id
            and item["model_id"] == focus_model_id
        ),
        None,
    )
    counts = {
        direction: sum(item["direction"] == direction for item in models)
        for direction in ("IMPROVED", "WORSENED", "UNCHANGED", "NOT_COMPARABLE")
    }
    return {
        "availability": "READY",
        "basis": "official_common_metrics",
        "direction_basis": "wape_pct",
        "source": _test_context(source),
        "retest": _test_context(retest),
        "model_set_match": set(source_models) == set(retest_models),
        "direction_counts": counts,
        "models": models,
        "focus_model": focus,
    }


def unavailable_retest_comparison(reason: str) -> dict:
    return {
        "availability": "NOT_AVAILABLE",
        "reason": reason,
        "basis": "official_common_metrics",
        "direction_basis": "wape_pct",
        "models": [],
        "focus_model": None,
    }


def _key(model: dict) -> tuple[str, str]:
    return model["provider_id"], model["model_id"]


def _model_delta(key: tuple[str, str], source: dict | None, retest: dict | None) -> dict:
    source_metrics = _metrics(source)
    retest_metrics = _metrics(retest)
    comparable = (
        source is not None
        and retest is not None
        and source["official_eligible"]
        and retest["official_eligible"]
        and source["wape_pct"] is not None
        and retest["wape_pct"] is not None
    )
    if not comparable:
        direction = "NOT_COMPARABLE"
    elif retest["wape_pct"] < source["wape_pct"]:
        direction = "IMPROVED"
    elif retest["wape_pct"] > source["wape_pct"]:
        direction = "WORSENED"
    else:
        direction = "UNCHANGED"
    return {
        "provider_id": key[0],
        "model_id": key[1],
        "direction": direction,
        "source": source_metrics,
        "retest": retest_metrics,
        "wape_change_pct_points": _change(source, retest, "wape_pct"),
        "mae_change": _change(source, retest, "mae"),
        "rmse_change": _change(source, retest, "rmse"),
        "abs_bias_change_pct_points": _absolute_change(
            source, retest, "bias_rate_pct"
        ),
        "success_rate_change_pct_points": _change(
            source, retest, "success_rate_pct"
        ),
        "rank_change": _change(source, retest, "rank"),
    }


def _metrics(model: dict | None) -> dict | None:
    if model is None:
        return None
    return {
        key: model.get(key)
        for key in (
            "official_eligible",
            "wape_pct",
            "mae",
            "rmse",
            "bias_rate_pct",
            "success_rate_pct",
            "rank",
        )
    }


def _change(source: dict | None, retest: dict | None, key: str):
    if source is None or retest is None:
        return None
    before = source.get(key)
    after = retest.get(key)
    if before is None or after is None:
        return None
    return after - before


def _absolute_change(source: dict | None, retest: dict | None, key: str):
    if source is None or retest is None:
        return None
    before = source.get(key)
    after = retest.get(key)
    if before is None or after is None:
        return None
    return abs(after) - abs(before)


def _test_context(test: dict) -> dict:
    return {
        key: test.get(key)
        for key in (
            "campaign_id",
            "comparison_id",
            "snapshot_id",
            "selection_version",
            "train_start",
            "train_end",
            "test_start",
            "test_end",
            "mode",
            "horizon",
        )
    }
