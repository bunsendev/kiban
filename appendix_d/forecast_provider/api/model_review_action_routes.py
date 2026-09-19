"""モデル精度変化レビューの対応タスクAPI。"""

from typing import Annotated

from fastapi import Depends, HTTPException, Query, status

from ..model_review import ActionConflict, ReviewActionNotFound, ReviewNotFound
from .model_review_action_schemas import ReviewActionCreate, ReviewActionEventCreate
from .schemas import Created
from .security import Permission, Principal


def install_model_review_action_routes(app, authorize, service) -> None:
    read = authorize.require(Permission.READ)
    approve = authorize.require(Permission.APPROVE)

    @app.post(
        "/api/model-drift-review-actions",
        response_model=Created,
        status_code=status.HTTP_201_CREATED,
    )
    def create_action(
        request: ReviewActionCreate,
        principal: Annotated[Principal, Depends(approve)],
    ):
        try:
            snapshot = service.create(request, principal.subject)
            return Created(id=snapshot.task.action_id)
        except ReviewNotFound as exc:
            raise HTTPException(status_code=404, detail="レビューが見つかりません") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/model-drift-review-actions/{action_id}/events")
    def append_action_event(
        action_id: str,
        request: ReviewActionEventCreate,
        principal: Annotated[Principal, Depends(approve)],
    ):
        try:
            return service.append(action_id, request, principal.subject).latest
        except ReviewActionNotFound as exc:
            raise HTTPException(status_code=404, detail="対応タスクが見つかりません") from exc
        except (ActionConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/model-drift-review-actions")
    def list_actions(
        _principal: Annotated[Principal, Depends(read)],
        review_id: Annotated[str | None, Query(pattern=r"^[0-9a-f-]{36}$")] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 200,
    ):
        return service.list(review_id=review_id, limit=limit)

    @app.get("/api/model-drift-review-action-events")
    def list_action_events(
        _principal: Annotated[Principal, Depends(read)],
        action_id: Annotated[str | None, Query(pattern=r"^[0-9a-f-]{36}$")] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 500,
    ):
        return service.list_events(action_id=action_id, limit=limit)
