"""mappingドライラン証跡のread-only API。"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status

from ..mapping_dry_run.catalog import MappingDryRunCatalog
from ..mapping_dry_run.evidence_schema import InvalidReportError
from .schemas import Created, MappingDryRunJobCreate
from .security import Permission, Principal


def install_mapping_dry_run_routes(
    app: FastAPI,
    authorize,
    catalog: MappingDryRunCatalog,
    jobs=None,
    mappings=None,
) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)

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
