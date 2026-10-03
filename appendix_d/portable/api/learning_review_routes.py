"""HTTP boundary for weekly SHADOW review snapshots and candidate decisions."""

import json

from fastapi import HTTPException, Request

from .learning_reviews import LearningReviewConflict, PortableWeeklyLearningReviews
from .production_handoff import ProductionHandoffError


def register_learning_review_routes(app, paths, read_limited) -> None:
    service = PortableWeeklyLearningReviews(
        paths.state / "shipment-actual-outcomes.sqlite3"
    )

    @app.get("/api/learning-reviews")
    def list_learning_reviews():
        return service.overview()

    @app.post("/api/learning-reviews", status_code=201)
    async def create_learning_review(request: Request):
        try:
            raw = await read_limited(request, 32 * 1024)
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise ProductionHandoffError("週次集計条件を確認してください")
            return service.create(payload)
        except (json.JSONDecodeError, ProductionHandoffError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/learning-reviews/{review_id}")
    def get_learning_review(review_id: str):
        try:
            return service.view(review_id)
        except ProductionHandoffError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/learning-candidates/{candidate_id}/decision", status_code=201)
    async def decide_learning_candidate(candidate_id: str, request: Request):
        try:
            raw = await read_limited(request, 16 * 1024)
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise ProductionHandoffError("改善候補の判断を確認してください")
            return service.decide(candidate_id, payload)
        except LearningReviewConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (json.JSONDecodeError, ProductionHandoffError) as exc:
            raise HTTPException(422, str(exc)) from exc
