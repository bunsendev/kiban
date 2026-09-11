"""Champion/challenger比較の昇格基準。"""

from __future__ import annotations

import math


def promotion_score(
    evaluations: list,
    champion_run_id: str,
    challenger_run_id: str,
    minimum_improvement_pct: float,
    maximum_failure_rate: float,
) -> dict:
    by_run = {value.run_id: value.score for value in evaluations}
    if champion_run_id not in by_run or challenger_run_id not in by_run:
        raise ValueError("比較にchampionとchallengerの両方が必要です")
    champion = by_run[champion_run_id]
    challenger = by_run[challenger_run_id]
    champion_metric = (champion.get("common_metrics") or {}).get("wape_pct")
    challenger_metric = (challenger.get("common_metrics") or {}).get("wape_pct")
    success_rate = challenger.get("run_success_rate")
    if champion_metric is None or challenger_metric is None or success_rate is None:
        return {
            "metric": "wape_pct",
            "champion_value": champion_metric,
            "challenger_value": challenger_metric,
            "improvement_pct": None,
            "minimum_improvement_pct": minimum_improvement_pct,
            "failure_rate": None if success_rate is None else 1 - float(success_rate),
            "maximum_failure_rate": maximum_failure_rate,
            "eligible": False,
            "reason": "COMMON_METRIC_OR_SUCCESS_RATE_MISSING",
        }
    champion_metric = float(champion_metric)
    challenger_metric = float(challenger_metric)
    success_rate = float(success_rate)
    if not all(
        math.isfinite(value) for value in (champion_metric, challenger_metric, success_rate)
    ):
        return {
            "metric": "wape_pct",
            "champion_value": None,
            "challenger_value": None,
            "improvement_pct": None,
            "minimum_improvement_pct": minimum_improvement_pct,
            "failure_rate": None,
            "maximum_failure_rate": maximum_failure_rate,
            "eligible": False,
            "reason": "COMMON_METRIC_OR_SUCCESS_RATE_INVALID",
        }
    improvement = (
        0.0
        if champion_metric == 0 and challenger_metric == 0
        else -100.0
        if champion_metric == 0
        else (champion_metric - challenger_metric) / champion_metric * 100
    )
    failure_rate = 1 - success_rate
    eligible = bool(
        improvement >= minimum_improvement_pct
        and failure_rate <= maximum_failure_rate
        and challenger_metric <= champion_metric
    )
    return {
        "metric": "wape_pct",
        "champion_value": champion_metric,
        "challenger_value": challenger_metric,
        "improvement_pct": improvement,
        "minimum_improvement_pct": minimum_improvement_pct,
        "failure_rate": failure_rate,
        "maximum_failure_rate": maximum_failure_rate,
        "eligible": eligible,
        "reason": None if eligible else "PROMOTION_THRESHOLD_NOT_MET",
    }
