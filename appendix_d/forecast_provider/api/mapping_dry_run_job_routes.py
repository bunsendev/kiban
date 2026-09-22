import csv
import io
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response, status

from .schemas import Created, MappingDryRunBatchCreate, MappingDryRunJobCreate
from .security import Permission, Principal


def install_mapping_dry_run_job_routes(
    app: FastAPI,
    authorize,
    *,
    jobs=None,
    mappings=None,
    sources=None,
) -> None:
    if jobs is None or mappings is None:
        return

    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)

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
        "/api/mapping-dry-run-batches",
        response_model=Created,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_mapping_dry_run_batch(
        request: MappingDryRunBatchCreate,
        principal: Annotated[Principal, Depends(analyze)],
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
    def get_mapping_dry_run_batch(
        batch_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        value = jobs.get_batch(batch_id)
        if value is None:
            raise HTTPException(status_code=404, detail="一括検証batchが見つかりません")
        return value

    @app.get("/api/mapping-dry-run-batches/{batch_id}/results.csv")
    def download_mapping_dry_run_batch(
        batch_id: str,
        _principal: Annotated[Principal, Depends(read)],
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
