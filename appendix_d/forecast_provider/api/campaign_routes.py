"""比較キャンペーンの認可済みAPI。"""

from typing import Annotated

from fastapi import Depends, HTTPException, Query, status

from .campaign_schemas import ComparisonCampaignBatchCreate, ComparisonCampaignCreate
from .campaign_service import CampaignNotFound
from .security import Permission, Principal
from .service import NotFoundError


def install_campaign_routes(app, authorize, service) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)

    @app.post("/api/comparison-campaigns", status_code=status.HTTP_202_ACCEPTED)
    def create_campaign(
        request: ComparisonCampaignCreate,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return service.create(request, principal.subject)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="snapshotが見つかりません") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/comparison-campaign-batches", status_code=status.HTTP_202_ACCEPTED)
    def create_campaign_batch(
        request: ComparisonCampaignBatchCreate,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return service.create_batch(request, principal.subject)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="snapshotが見つかりません") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/comparison-campaign-results")
    def list_campaign_results(
        _principal: Annotated[Principal, Depends(read)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        return service.result_matrix(limit=limit)

    @app.get("/api/comparison-campaigns")
    def list_campaigns(
        _principal: Annotated[Principal, Depends(read)],
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ):
        return service.list(limit=limit)

    @app.get("/api/comparison-campaigns/{campaign_id}")
    def get_campaign(
        campaign_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            return service.detail(campaign_id)
        except CampaignNotFound as exc:
            raise HTTPException(status_code=404, detail="比較キャンペーンが見つかりません") from exc

    @app.post("/api/comparison-campaigns/{campaign_id}/retry-finalization")
    def retry_campaign_finalization(
        campaign_id: str,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return service.retry_finalization(campaign_id)
        except CampaignNotFound as exc:
            raise HTTPException(status_code=404, detail="比較キャンペーンが見つかりません") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
