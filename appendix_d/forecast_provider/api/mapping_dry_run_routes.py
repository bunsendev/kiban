import csv
import io
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status

from ..mapping_dry_run.catalog import MappingDryRunCatalog
from ..mapping_dry_run.evidence_schema import InvalidReportError
from ..mapping_dry_run.inventory_profiles import InventoryProfileError
from ..mapping_dry_run.uploads import SourceUploadError
from .schemas import (
    Created,
    InventoryNormalizationDecisionCreate,
    InventoryNormalizationJobCreate,
    InventoryNormalizationPreviewCreate,
    InventoryProfileCreate,
    MappingDryRunBatchCreate,
    MappingDryRunJobCreate,
)
from .security import Permission, Principal, audit_payload


def install_mapping_dry_run_routes(
    app: FastAPI,
    authorize,
    catalog: MappingDryRunCatalog,
    jobs=None,
    mappings=None,
    sources=None,
    uploader=None,
    bulk_uploader=None,
    inventory_profiler=None,
    product_bridge=None,
    inventory_preview=None,
    inventory_normalization=None,
) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)
    approve = authorize.require(Permission.APPROVE)
    export = authorize.require(Permission.EXPORT)

    @app.get("/api/mapping-dry-runs")
    def list_mapping_dry_runs(
        _principal: Annotated[Principal, Depends(read)],
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ):
        return catalog.list_reports(limit)

    @app.get("/api/mapping-dry-runs/{report_sha256}")
    def get_mapping_dry_run(
        report_sha256: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            report = catalog.get_report(report_sha256)
        except InvalidReportError as exc:
            raise HTTPException(
                status_code=409, detail="証跡のchecksumまたは形式が不正です"
            ) from exc
        if report is None:
            raise HTTPException(status_code=404, detail="mappingドライラン証跡が見つかりません")
        return report

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
            content_length = request.headers.get("content-length")
            try:
                length = int(content_length) if content_length is not None else None
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Content-Lengthが不正です") from exc
            if length is not None and length < 0:
                raise HTTPException(status_code=400, detail="Content-Lengthが不正です")
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
            content_length = request.headers.get("content-length")
            try:
                length = int(content_length) if content_length is not None else None
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Content-Lengthが不正です") from exc
            if length is not None and length < 0:
                raise HTTPException(status_code=400, detail="Content-Lengthが不正です")
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

    if inventory_normalization is not None:

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

        @app.get("/api/inventory-normalization-jobs/{job_id}/results")
        def get_inventory_normalization_results(
            job_id: str,
            _principal: Annotated[Principal, Depends(read)],
            limit: Annotated[int, Query(ge=1, le=500)] = 100,
            offset: Annotated[int, Query(ge=0)] = 0,
        ):
            job = inventory_normalization.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="在庫正規化jobが見つかりません")
            if job["status"] != "SUCCEEDED":
                raise HTTPException(status_code=409, detail="在庫正規化jobが完了していません")
            results = inventory_normalization.results(job_id, limit, offset)
            if results is None:
                raise HTTPException(status_code=409, detail="数量照合情報がありません")
            return results

        @app.get("/api/inventory-normalization-jobs/{job_id}/results.csv")
        def download_inventory_normalization_results(
            job_id: str,
            _principal: Annotated[Principal, Depends(export)],
        ):
            job = inventory_normalization.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="在庫正規化jobが見つかりません")
            if job["status"] != "SUCCEEDED":
                raise HTTPException(status_code=409, detail="在庫正規化jobが完了していません")
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

    if jobs is None or mappings is None:
        return

    @app.post(
        "/api/mapping-dry-run-jobs",
        response_model=Created,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_mapping_dry_run_job(
        request: MappingDryRunJobCreate,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        if mappings.get_mapping(request.mapping_id) is None:
            raise HTTPException(status_code=422, detail="mappingが見つかりません")
        value = jobs.enqueue(
            request.source_path,
            request.mapping_id,
            principal.subject,
            request.sample_rows,
        )
        return Created(id=value.job_id)

    @app.get("/api/mapping-dry-run-jobs")
    def list_mapping_dry_run_jobs(
        _principal: Annotated[Principal, Depends(read)],
    ):
        return [value.__dict__ for value in jobs.list_jobs()]

    @app.get("/api/mapping-dry-run-jobs/{job_id}")
    def get_mapping_dry_run_job(
        job_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        value = jobs.get_job(job_id)
        if value is None:
            raise HTTPException(status_code=404, detail="mappingドライランjobが見つかりません")
        return value.__dict__

    @app.post(
        "/api/mapping-dry-run-batches", response_model=Created, status_code=status.HTTP_202_ACCEPTED
    )
    def create_mapping_dry_run_batch(
        request: MappingDryRunBatchCreate, principal: Annotated[Principal, Depends(analyze)]
    ):
        if mappings.get_mapping(request.mapping_id) is None:
            raise HTTPException(status_code=422, detail="mappingが見つかりません")
        paths = sources.paths_under(request.source_prefix)
        selected = [path for path in paths if "出荷" in path.rsplit("/", 1)[-1]]
        if not selected:
            raise HTTPException(status_code=422, detail="ファイル名に「出荷」を含むCSVがありません")
        value = jobs.enqueue_batch(
            request.source_prefix,
            selected,
            request.mapping_id,
            principal.subject,
            request.sample_rows,
            len(paths) - len(selected),
        )
        return Created(id=value.batch_id)

    @app.get("/api/mapping-dry-run-batches/{batch_id}")
    def get_mapping_dry_run_batch(batch_id: str, _principal: Annotated[Principal, Depends(read)]):
        value = jobs.get_batch(batch_id)
        if value is None:
            raise HTTPException(status_code=404, detail="一括検証batchが見つかりません")
        return value

    @app.get("/api/mapping-dry-run-batches/{batch_id}/results.csv")
    def download_mapping_dry_run_batch(
        batch_id: str, _principal: Annotated[Principal, Depends(read)]
    ):
        value = jobs.get_batch(batch_id)
        if value is None:
            raise HTTPException(status_code=404, detail="一括検証batchが見つかりません")
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(["source_path", "status", "outcome", "error_code", "report_sha256"])
        for job in value["jobs"]:
            writer.writerow(
                [
                    job["source_path"],
                    job["status"],
                    job["outcome"] or "",
                    job["error_code"] or "",
                    job["report_sha256"] or "",
                ]
            )
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="batch-{batch_id}.csv"'},
        )
