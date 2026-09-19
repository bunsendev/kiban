"""完了済み比較キャンペーンの横断結果と安定性集計。"""

from statistics import fmean, pstdev


def build_campaign_results(campaigns, application, evaluation, *, limit: int) -> dict:
    """保存済み公式指標をsnapshot条件と結合して返す。"""
    if evaluation is None:
        return {"tests": [], "model_stability": _stability([])}
    tests = []
    for campaign in campaigns.list(limit=limit):
        finalization = campaigns.get_finalization(campaign.campaign_id)
        if finalization is None or finalization.status != "SUCCEEDED":
            continue
        snapshot = application.get_snapshot(campaign.snapshot_id)
        comparison = evaluation.comparison_detail(finalization.comparison_id)
        scores = comparison["result"].get("scores", {})
        models = _models(campaigns.list_entries(campaign.campaign_id), scores)
        manifest = snapshot.manifest
        tests.append(
            {
                "campaign_id": campaign.campaign_id,
                "comparison_id": finalization.comparison_id,
                "purpose": campaign.purpose,
                "snapshot_id": campaign.snapshot_id,
                "selection_version": manifest["selection_version"],
                "train_start": manifest["train_start"],
                "train_end": manifest["train_end"],
                "test_start": manifest["test_start"],
                "test_end": manifest["test_end"],
                "origin_interval_days": manifest["origin_interval_days"],
                "max_horizon": manifest["max_horizon"],
                "primary_horizon_max": manifest["primary_horizon_max"],
                "mode": finalization.mode,
                "horizon": finalization.horizon,
                "created_at": campaign.created_at,
                "models": models,
            }
        )
    return {"tests": tests, "model_stability": _stability(tests)}


def summarize_model_stability(tests: list[dict]) -> dict:
    """純粋関数として、条件間の順位と精度の分布を集計する。"""
    return _stability(tests)


def _models(entries, scores: dict) -> list[dict]:
    models = []
    for entry in entries:
        score = scores.get(entry.run_id, {})
        metrics = score.get("official_common_metrics")
        models.append(
            {
                "provider_id": entry.provider_id,
                "model_id": entry.model_id,
                "run_id": entry.run_id,
                "official_eligible": bool(score.get("official_eligible")),
                "wape_pct": None if metrics is None else metrics.get("wape_pct"),
                "mae": None if metrics is None else metrics.get("mae"),
                "rmse": None if metrics is None else metrics.get("rmse"),
                "bias_rate_pct": None if metrics is None else metrics.get("bias_rate_pct"),
                "success_rate_pct": (
                    None
                    if score.get("run_success_rate") is None
                    else score["run_success_rate"] * 100
                ),
                "rank": None,
            }
        )
    ranked = sorted(
        (
            item
            for item in models
            if item["official_eligible"] and item["wape_pct"] is not None
        ),
        key=lambda item: (item["wape_pct"], item["provider_id"], item["model_id"]),
    )
    for rank, item in enumerate(ranked, 1):
        item["rank"] = rank
    return models


def _stability(tests: list[dict]) -> dict:
    buckets = {}
    for test in tests:
        for model in test["models"]:
            key = (model["provider_id"], model["model_id"])
            bucket = buckets.setdefault(
                key,
                {"configured": 0, "ranks": [], "wapes": [], "biases": [], "success": []},
            )
            bucket["configured"] += 1
            if (
                not model["official_eligible"]
                or model["wape_pct"] is None
                or model["rank"] is None
            ):
                continue
            bucket["ranks"].append(model["rank"])
            bucket["wapes"].append(model["wape_pct"])
            if model["bias_rate_pct"] is not None:
                bucket["biases"].append(abs(model["bias_rate_pct"]))
            if model["success_rate_pct"] is not None:
                bucket["success"].append(model["success_rate_pct"])

    total = len(tests)
    models = []
    for (provider_id, model_id), values in buckets.items():
        configured = values["configured"]
        ranks = values["ranks"]
        wapes = values["wapes"]
        eligible = len(wapes)
        rank_min = min(ranks) if ranks else None
        rank_max = max(ranks) if ranks else None
        models.append(
            {
                "provider_id": provider_id,
                "model_id": model_id,
                "completed_test_count": total,
                "configured_test_count": configured,
                "eligible_test_count": eligible,
                "official_coverage_pct": _rate(eligible, configured),
                "overall_coverage_pct": _rate(eligible, total),
                "win_count": sum(rank == 1 for rank in ranks),
                "win_rate_pct": _rate(sum(rank == 1 for rank in ranks), eligible),
                "mean_rank": _mean(ranks),
                "rank_stddev": _stddev(ranks),
                "rank_min": rank_min,
                "rank_max": rank_max,
                "rank_range": None if rank_min is None else rank_max - rank_min,
                "varies_by_condition": len(set(ranks)) > 1,
                "wape_mean_pct": _mean(wapes),
                "wape_min_pct": min(wapes) if wapes else None,
                "wape_max_pct": max(wapes) if wapes else None,
                "wape_stddev_pct": _stddev(wapes),
                "wape_range_pct": None if not wapes else max(wapes) - min(wapes),
                "mean_abs_bias_rate_pct": _mean(values["biases"]),
                "min_success_rate_pct": min(values["success"]) if values["success"] else None,
            }
        )
    models.sort(
        key=lambda item: (
            -item["official_coverage_pct"],
            -(item["eligible_test_count"]),
            item["mean_rank"] if item["mean_rank"] is not None else float("inf"),
            item["wape_mean_pct"] if item["wape_mean_pct"] is not None else float("inf"),
            item["provider_id"],
            item["model_id"],
        )
    )
    return {"completed_test_count": total, "models": models}


def _rate(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator * 100


def _mean(values: list[float]) -> float | None:
    return None if not values else fmean(values)


def _stddev(values: list[float]) -> float | None:
    return None if not values else pstdev(values)
