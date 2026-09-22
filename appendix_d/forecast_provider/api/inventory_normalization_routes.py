import csv
import io
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status

from ..inventory_normalization.export import feature_view_csv
from .schemas import (
    Created,
    InventoryFeatureViewCreate,
    InventoryNormalizationDecisionCreate,
    InventoryNormalizationJobCreate,
)
from .security import Permission, Principal, audit_payload


def install_inventory_normalization_routes(
    app: FastAPI,
    authorize,
    inventory_normalization=None,
) -> None:
    if inventory_normalization is None:
        return

    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)
    approve = authorize.require(Permission.APPROVE)
    export = authorize.require(Permission.EXPORT)

    @app.post(
        "/api/inventory-normalization-jobs",
        response_model=Created,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_inventory_normalization_job(
        request: InventoryNormalizationJobCreate,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        job_id = inventory_normalization.enqueue(
            request.source_prefix,
            request.product_mapping_id,
            request.unit_value,
            principal.subject,
        )
        return Created(id=job_id)

    @app.get("/api/inventory-normalization-jobs")
    def list_inventory_normalization_jobs(
        _principal: Annotated[Principal, Depends(read)],
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ):
        return inventory_normalization.list_jobs(limit)

    @app.get("/api/inventory-normalization-jobs/{job_id}")
    def get_inventory_normalization_job(
        job_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        value = inventory_normalization.get(job_id)
        if value is None:
            raise HTTPException(status_code=404, detail="在庫正規化jobが見つかりません")
        return value

    @app.post(
        "/api/inventory-normalization-jobs/{job_id}/decisions",
        response_model=Created,
        status_code=status.HTTP_201_CREATED,
    )
    def decide_inventory_normalization_job(
        job_id: str,
        request: InventoryNormalizationDecisionCreate,
        principal: Annotated[Principal, Depends(approve)],
    ):
        try:
            decision_id = inventory_normalization.decide(
                job_id=job_id,
                **audit_payload(request, principal, "decided_by"),
            )
            return Created(id=decision_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/inventory-normalization-jobs/{job_id}/decisions")
    def list_inventory_normalization_decisions(
        job_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        if inventory_normalization.get(job_id) is None:
            raise HTTPException(status_code=404, detail="在庫正規化jobが見つかりません")
        return inventory_normalization.list_decisions(job_id)

    @app.get("/api/inventory-normalization-adoption")
    def get_inventory_normalization_adoption(
        _principal: Annotated[Principal, Depends(read)],
    ):
        return {"current": inventory_normalization.current_adoption()}

    @app.post("/api/inventory-feature-views")
    def create_inventory_feature_view(
        request: InventoryFeatureViewCreate,
        _principal: Annotated[Principal, Depends(read)],
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        try:
            return inventory_normalization.feature_view(
                request.mapping_version,
                request.as_of.isoformat(),
                limit,
                offset,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/inventory-feature-views.csv")
    def download_inventory_feature_view(
        mapping_version: Annotated[str, Query(min_length=1, max_length=100)],
        as_of: datetime,
        _principal: Annotated[Principal, Depends(export)],
    ):
        try:
            view = inventory_normalization.feature_view(
                mapping_version,
                as_of.isoformat(),
                2_147_483_647,
                0,
            )
            content, checksum = feature_view_csv(view)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(
            content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="inventory-feature-{view["view_id"]}.csv"'
                ),
                "X-Kiban-Feature-View-ID": view["view_id"],
                "X-Content-SHA256": checksum,
            },
        )

    @app.post("/api/inventory-feature-exports", status_code=status.HTTP_201_CREATED)
    def publish_inventory_feature_export(
        request: InventoryFeatureViewCreate,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return inventory_normalization.publish_feature_export(
                request.mapping_version,
                request.as_of.isoformat(),
                principal.subject,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/inventory-feature-exports")
    def list_inventory_feature_exports(
        _principal: Annotated[Principal, Depends(read)],
    ):
        return inventory_normalization.list_feature_exports()

    @app.get("/api/inventory-feature-exports/{export_id}")
    def download_published_inventory_feature_export(
        export_id: str,
        _principal: Annotated[Principal, Depends(export)],
    ):
        try:
            result = inventory_normalization.feature_export_content(export_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="在庫特徴CSV発行記録が見つかりません")
        record, content = result
        return Response(
            content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{export_id}.csv"',
                "X-Kiban-Feature-View-ID": record["view_id"],
                "X-Content-SHA256": record["content_sha256"],
            },
        )

    @app.get("/api/inventory-normalization-jobs/{job_id}/results")
    def get_inventory_normalization_results(
        job_id: str,
        _principal: Annotated[Principal, Depends(read)],
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        _completed_job(inventory_normalization, job_id)
        results = inventory_normalization.results(job_id, limit, offset)
        if results is None:
            raise HTTPException(status_code=409, detail="数量照合情報がありません")
        return results

    @app.get("/api/inventory-normalization-jobs/{job_id}/results.csv")
    def download_inventory_normalization_results(
        job_id: str,
        _principal: Annotated[Principal, Depends(export)],
    ):
        _completed_job(inventory_normalization, job_id)
        if inventory_normalization.results(job_id, 1, 0) is None:
            raise HTTPException(status_code=409, detail="数量照合情報がありません")
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(["在庫日", "JAN", "倉庫コード", "単位", "数量"])
        for value in inventory_normalization.list_values(job_id):
            writer.writerow(
                [
                    value["inventory_date"],
                    value["jan"],
                    value["center_id"],
                    value["unit"],
                    value["quantity"],
                ]
            )
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="inventory-normalized-{job_id}.csv"'
                )
            },
        )


def _completed_job(inventory_normalization, job_id: str) -> dict:
    job = inventory_normalization.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="在庫正規化jobが見つかりません")
    if job["status"] != "SUCCEEDED":
        raise HTTPException(status_code=409, detail="在庫正規化jobが完了していません")
    return job
