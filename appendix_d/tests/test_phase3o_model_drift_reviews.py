"""Phase 3O: モデル精度変化の版付き調査・判断台帳。"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from forecast_provider.api.authentication import Authorizer, TokenAuthenticator
from forecast_provider.api.model_review_routes import install_model_review_routes
from forecast_provider.api.model_review_schemas import ModelDriftReviewCreate
from forecast_provider.model_review import (
    ModelDriftReviewService,
    ReviewHistoryRequired,
    ReviewProfileNotFound,
    SqliteModelReviewStore,
    make_model_drift_review,
)

PROFILE_ID = "a" * 64


def _series(*, profile_id: str = PROFILE_ID, history_count: int = 2) -> dict:
    previous = None
    if history_count >= 2:
        previous = {
            "campaign_id": "campaign-1",
            "selection_version": "selection-v1",
            "test_start": "2026-07-01",
            "test_end": "2026-07-30",
            "created_at": "2026-09-18T00:00:00+00:00",
            "wape_pct": 10.0,
            "bias_rate_pct": -2.0,
            "success_rate_pct": 100.0,
            "rank": 1,
        }
    return {
        "comparison_profile_id": profile_id,
        "provider_id": "provider",
        "model_id": "model",
        "population_size": 3,
        "train_days": 365,
        "test_days": 30,
        "availability_mode": "OBSERVED",
        "mode": "primary",
        "horizon": None,
        "origin_interval_days": 7,
        "max_horizon": 7,
        "primary_horizon_max": 7,
        "history_count": history_count,
        "previous": previous,
        "latest": {
            "campaign_id": "campaign-2",
            "selection_version": "selection-v2",
            "test_start": "2026-08-01",
            "test_end": "2026-08-30",
            "created_at": "2026-09-19T00:00:00+00:00",
            "wape_pct": 12.0,
            "bias_rate_pct": 3.0,
            "success_rate_pct": 98.0,
            "rank": 2,
        },
        "wape_change_pct_points": None if previous is None else 2.0,
        "wape_relative_change_pct": None if previous is None else 20.0,
        "abs_bias_change_pct_points": None if previous is None else 1.0,
        "success_rate_change_pct_points": None if previous is None else -2.0,
        "rank_change": None if previous is None else 1,
        "period_gap_days": None if previous is None else 1,
        "direction": "INSUFFICIENT_HISTORY" if previous is None else "WAPE_UP",
    }


class _CampaignResults:
    def __init__(self, series: list[dict]) -> None:
        self.series = series

    def result_matrix(self, *, limit: int) -> dict:
        assert limit == 200
        return {"model_drift": {"series": self.series}}


def _request(**values) -> ModelDriftReviewCreate:
    return ModelDriftReviewCreate(
        comparison_profile_id=values.get("comparison_profile_id", PROFILE_ID),
        decision_version=values.get("decision_version", "review-v1"),
        conclusion=values.get("conclusion", "INVESTIGATING"),
        reason=values.get("reason", "WAPE上昇の原因を確認中"),
        action=values.get("action", "データ品質と業務イベントを照合する"),
    )


def test_review_freezes_evidence_and_store_is_append_only(tmp_path) -> None:
    store = SqliteModelReviewStore(tmp_path / "review.sqlite3")
    evidence = _series()
    first = make_model_drift_review(
        PROFILE_ID,
        "review-v1",
        "INVESTIGATING",
        "reviewer",
        "原因を確認中",
        "データ品質を確認する",
        evidence,
    )
    store.put(first)
    evidence["latest"]["wape_pct"] = 999

    assert store.list()[0].evidence["latest"]["wape_pct"] == 12
    duplicate = make_model_drift_review(
        PROFILE_ID,
        "review-v1",
        "NO_ACTION",
        "reviewer",
        "問題なし",
        "追加対応なし",
        _series(),
    )
    with pytest.raises(ValueError, match="変更できません"):
        store.put(duplicate)

    second = make_model_drift_review(
        PROFILE_ID,
        "review-v2",
        "DATA_ISSUE",
        "reviewer",
        "欠測増加を確認",
        "入力データを修正する",
        _series(),
    )
    store.put(second)
    assert {item.decision_version for item in store.list()} == {"review-v1", "review-v2"}


def test_service_requires_current_profile_and_authenticated_subject(tmp_path) -> None:
    store = SqliteModelReviewStore(tmp_path / "review.sqlite3")
    service = ModelDriftReviewService(store, _CampaignResults([_series()]))

    value = service.create(_request(), "authenticated-reviewer")

    assert value.reviewed_by == "authenticated-reviewer"
    assert value.evidence["previous"]["campaign_id"] == "campaign-1"
    assert value.evidence["latest"]["campaign_id"] == "campaign-2"
    assert len(value.evidence_sha256) == 64
    with pytest.raises(ReviewProfileNotFound):
        service.create(_request(comparison_profile_id="b" * 64), "reviewer")

    insufficient = ModelDriftReviewService(store, _CampaignResults([_series(history_count=1)]))
    with pytest.raises(ReviewHistoryRequired, match="2件以上"):
        insufficient.create(_request(decision_version="review-v2"), "reviewer")


def test_review_api_requires_approve_and_returns_versioned_history(tmp_path) -> None:
    store = SqliteModelReviewStore(tmp_path / "review.sqlite3")
    service = ModelDriftReviewService(store, _CampaignResults([_series()]))
    app = FastAPI()
    install_model_review_routes(
        app,
        Authorizer(TokenAuthenticator.single("token", "api-reviewer")),
        service,
    )
    api = TestClient(app)
    payload = _request().model_dump(mode="json")

    assert api.post("/api/model-drift-reviews", json=payload).status_code == 401
    api.headers["Authorization"] = "Bearer token"
    created = api.post("/api/model-drift-reviews", json=payload)
    assert created.status_code == 201, created.text
    history = api.get("/api/model-drift-reviews").json()
    assert len(history) == 1
    assert history[0]["reviewed_by"] == "api-reviewer"
    assert history[0]["evidence"]["direction"] == "WAPE_UP"
    assert api.post("/api/model-drift-reviews", json=payload).status_code == 409


def test_domain_rejects_profile_or_evidence_mismatch() -> None:
    with pytest.raises(ValueError, match="profile_id"):
        make_model_drift_review(
            "invalid",
            "v1",
            "NO_ACTION",
            "reviewer",
            "問題なし",
            "対応なし",
            _series(),
        )
    with pytest.raises(ValueError, match="証跡"):
        make_model_drift_review(
            PROFILE_ID,
            "v1",
            "NO_ACTION",
            "reviewer",
            "問題なし",
            "対応なし",
            {"comparison_profile_id": "b" * 64},
        )
