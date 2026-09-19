"""レビュー対応から追加テストを実行・参照するAPI。"""

from typing import Annotated

from fastapi import Depends, HTTPException, Query, status

from ..model_review import ActionConflict, ReviewActionNotFound
from .campaign_service import CampaignNotFound
from .model_review_retest_schemas import ReviewRetestCreate
from .security import Permission, Principal
from .service import NotFoundError


def install_model_review_retest_routes(app, authorize, service) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)

    @app.post(
        "/api/model-drift-review-actions/{action_id}/retests",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_retest(
        action_id: str,
        request: ReviewRetestCreate,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return service.start(action_id, request, principal.subject)
        except ReviewActionNotFound as exc:
            raise HTTPException(status_code=404, detail="対応タスクが見つかりません") from exc
        except (CampaignNotFound, NotFoundError) as exc:
            raise HTTPException(
                status_code=404, detail="比較キャンペーンまたはデータセットが見つかりません"
            ) from exc
        except ActionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/model-drift-review-retests")
    def list_retests(
        _principal: Annotated[Principal, Depends(read)],
        action_id: Annotated[str | None, Query(pattern=r"^[0-9a-f-]{36}$")] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 200,
    ):
        return service.list(action_id=action_id, limit=limit)
