"""モデル精度変化レビューの認可済みAPI。"""

from typing import Annotated

from fastapi import Depends, HTTPException, Query, status

from ..model_review import ReviewHistoryRequired, ReviewProfileNotFound
from .model_review_schemas import ModelDriftReviewCreate
from .schemas import Created
from .security import Permission, Principal


def install_model_review_routes(app, authorize, service) -> None:
    read = authorize.require(Permission.READ)
    approve = authorize.require(Permission.APPROVE)

    @app.post(
        "/api/model-drift-reviews",
        response_model=Created,
        status_code=status.HTTP_201_CREATED,
    )
    def create_review(
        request: ModelDriftReviewCreate,
        principal: Annotated[Principal, Depends(approve)],
    ):
        try:
            value = service.create(request, principal.subject)
            return Created(id=value.review_id)
        except ReviewProfileNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="比較プロフィールが現在の公式結果に見つかりません",
            ) from exc
        except (ReviewHistoryRequired, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/model-drift-reviews")
    def list_reviews(
        _principal: Annotated[Principal, Depends(read)],
        comparison_profile_id: Annotated[
            str | None,
            Query(pattern=r"^[0-9a-f]{64}$"),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 200,
    ):
        return service.list(
            comparison_profile_id=comparison_profile_id,
            limit=limit,
        )
