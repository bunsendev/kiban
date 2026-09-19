"""現在の公式結果と照合してモデル精度変化レビューを記録する。"""

from dataclasses import asdict

from .domain import make_model_drift_review


class ReviewProfileNotFound(KeyError):
    pass


class ReviewHistoryRequired(ValueError):
    pass


class ModelDriftReviewService:
    def __init__(self, store, campaigns) -> None:
        self.store = store
        self.campaigns = campaigns

    def create(self, request, reviewed_by: str):
        drift = self.campaigns.result_matrix(limit=200)["model_drift"]
        series = next(
            (
                item
                for item in drift["series"]
                if item["comparison_profile_id"] == request.comparison_profile_id
            ),
            None,
        )
        if series is None:
            raise ReviewProfileNotFound(request.comparison_profile_id)
        if series["history_count"] < 2:
            raise ReviewHistoryRequired("異なるテスト期間が2件以上ある系列だけをレビューできます")
        value = make_model_drift_review(
            comparison_profile_id=request.comparison_profile_id,
            decision_version=request.decision_version,
            conclusion=request.conclusion,
            reviewed_by=reviewed_by,
            reason=request.reason,
            action=request.action,
            evidence=_evidence(series),
        )
        return self.store.put(value)

    def list(self, *, comparison_profile_id: str | None = None, limit: int = 200) -> list[dict]:
        return [
            asdict(item)
            for item in self.store.list(
                comparison_profile_id=comparison_profile_id,
                limit=limit,
            )
        ]


def _evidence(series: dict) -> dict:
    names = (
        "comparison_profile_id",
        "provider_id",
        "model_id",
        "population_size",
        "train_days",
        "test_days",
        "availability_mode",
        "mode",
        "horizon",
        "origin_interval_days",
        "max_horizon",
        "primary_horizon_max",
        "history_count",
        "previous",
        "latest",
        "wape_change_pct_points",
        "wape_relative_change_pct",
        "abs_bias_change_pct_points",
        "success_rate_change_pct_points",
        "rank_change",
        "period_gap_days",
        "direction",
    )
    return {name: series[name] for name in names}
