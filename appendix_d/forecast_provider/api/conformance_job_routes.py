"""Provider適合試験jobの認可済みHTTP API。"""

from dataclasses import asdict
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status

from ..provider_conformance.service import ConformanceJobNotFound
from .evaluation_schemas import ConformanceJobCreate
from .security import Permission, Principal


def install_conformance_job_routes(app, authorize, service) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)

    @app.post(
        "/api/provider-conformance-jobs",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_job(
        request: ConformanceJobCreate,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return asdict(service.enqueue(request.experiment_id, principal.subject))
        except ConformanceJobNotFound as exc:
            raise HTTPException(status_code=404, detail="実験条件が見つかりません") from exc

    @app.get("/api/provider-conformance-jobs")
    def list_jobs(
        _principal: Annotated[Principal, Depends(read)],
        experiment_id: Annotated[str | None, Query(min_length=1)] = None,
    ):
        try:
            return [asdict(item) for item in service.list(experiment_id)]
        except ConformanceJobNotFound as exc:
            raise HTTPException(status_code=404, detail="実験条件が見つかりません") from exc

    @app.get("/api/provider-conformance-jobs/{job_id}")
    def get_job(
        job_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            return asdict(service.get(job_id))
        except ConformanceJobNotFound as exc:
            raise HTTPException(status_code=404, detail="適合試験jobが見つかりません") from exc
