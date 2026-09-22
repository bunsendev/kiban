from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status

from ..mapping_dry_run.inventory_profiles import InventoryProfileError
from ..mapping_dry_run.uploads import SourceUploadError
from .schemas import InventoryNormalizationPreviewCreate, InventoryProfileCreate
from .security import Permission, Principal


def install_mapping_dry_run_source_routes(
    app: FastAPI,
    authorize,
    *,
    sources=None,
    uploader=None,
    bulk_uploader=None,
    inventory_profiler=None,
    product_bridge=None,
    inventory_preview=None,
) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)

    if sources is not None:

        @app.get("/api/mapping-dry-run-sources")
        def list_mapping_dry_run_sources(
            _principal: Annotated[Principal, Depends(read)],
            limit: Annotated[int, Query(ge=1, le=500)] = 200,
            source_path: Annotated[str | None, Query(max_length=500)] = None,
        ):
            if source_path is not None:
                return sources.get_source(source_path)
            return sources.list_sources(limit)

    if uploader is not None:

        @app.post("/api/mapping-dry-run-uploads", status_code=status.HTTP_201_CREATED)
        async def upload_mapping_dry_run_source(
            request: Request,
            principal: Annotated[Principal, Depends(analyze)],
            filename: Annotated[str, Query(min_length=1, max_length=120)],
        ):
            length = _content_length(request)
            try:
                result = await uploader.save(filename, request.stream(), length)
            except SourceUploadError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {**result, "uploaded_by": principal.subject}

    if bulk_uploader is not None:

        @app.post("/api/mapping-dry-run-bulk-uploads", status_code=status.HTTP_201_CREATED)
        async def upload_mapping_dry_run_batch(
            request: Request,
            principal: Annotated[Principal, Depends(analyze)],
            filename: Annotated[str, Query(min_length=1, max_length=120)],
        ):
            length = _content_length(request)
            try:
                result = await bulk_uploader.save(filename, request.stream(), length)
            except SourceUploadError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {**result, "uploaded_by": principal.subject}

    if inventory_profiler is not None:

        @app.post("/api/inventory-structure-profiles")
        def create_inventory_structure_profile(
            request: InventoryProfileCreate,
            _principal: Annotated[Principal, Depends(analyze)],
        ):
            try:
                return inventory_profiler.profile(request.source_prefix)
            except InventoryProfileError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if product_bridge is not None:

        @app.post("/api/product-jan-bridge-analysis")
        def analyze_product_jan_bridge(
            request: InventoryProfileCreate,
            _principal: Annotated[Principal, Depends(analyze)],
        ):
            try:
                return product_bridge.analyze(request.source_prefix)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        @app.get("/api/product-jan-bridge-template.csv")
        def download_product_jan_bridge_template(
            source_prefix: Annotated[str, Query(min_length=1, max_length=1_024)],
            _principal: Annotated[Principal, Depends(read)],
        ):
            try:
                content = product_bridge.template(source_prefix)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return Response(
                content,
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="product-jan-mapping.csv"'},
            )

        @app.post("/api/product-jan-mappings", status_code=status.HTTP_201_CREATED)
        async def import_product_jan_mapping(
            request: Request,
            source_prefix: Annotated[str, Query(min_length=1, max_length=1_024)],
            _principal: Annotated[Principal, Depends(analyze)],
        ):
            content = await request.body()
            try:
                return product_bridge.import_mapping(source_prefix, content)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if inventory_preview is not None:

        @app.post("/api/inventory-normalization-previews")
        def create_inventory_normalization_preview(
            request: InventoryNormalizationPreviewCreate,
            _principal: Annotated[Principal, Depends(analyze)],
        ):
            try:
                return inventory_preview.run(
                    request.source_prefix,
                    request.product_mapping_id,
                    request.unit_value,
                    request.sample_rows,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc


def _content_length(request: Request) -> int | None:
    content_length = request.headers.get("content-length")
    try:
        length = int(content_length) if content_length is not None else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Content-Lengthが不正です") from exc
    if length is not None and length < 0:
        raise HTTPException(status_code=400, detail="Content-Lengthが不正です")
    return length
