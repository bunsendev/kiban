from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status

from ..errors import ContractViolationError
from .schemas import (
    Created,
    ExperimentCreate,
    ResumeInput,
    RunCreate,
    RunCreated,
    RunStatusOutput,
    SnapshotCreate,
)
from .security import Permission, Principal
from .service import ApplicationService, NotFoundError, record_dict


def _run_output(value, resource_cost=None) -> RunStatusOutput:
    return RunStatusOutput(
        run_id=value.run_id,
        experiment_id=value.experiment_id,
        status=value.status,
        cancellation_requested=value.cancellation_requested,
        origin_counts=value.origin_counts,
        failure_count=value.failure_count,
        provider_id=value.provider_id,
        model_name=value.model_name,
        resources=None if resource_cost is None else resource_cost.summarize(value.run_id),
    )


def install_core_routes(
    app: FastAPI,
    authorize,
    service: ApplicationService,
    resource_cost=None,
) -> None:
    """Install health, session, catalog, and forecast-run endpoints."""

    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/session")
    def get_session(principal: Annotated[Principal, Depends(authorize)]):
        return {
            "subject": principal.subject,
            "roles": [role.value for role in principal.roles],
            "permissions": sorted(permission.value for permission in principal.permissions),
        }

    @app.post("/api/snapshots", response_model=Created, status_code=201)
    def create_snapshot(
        request: SnapshotCreate,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return Created(id=service.create_snapshot(request).snapshot_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(
        snapshot_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            return record_dict(service.get_snapshot(snapshot_id))
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="snapshotが見つかりません") from exc

    @app.get("/api/snapshots")
    def list_snapshots(
        _principal: Annotated[Principal, Depends(read)],
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ):
        return [record_dict(value) for value in service.list_snapshots(limit=limit)]

    @app.post("/api/experiments", response_model=Created, status_code=201)
    def create_experiment(
        request: ExperimentCreate,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return Created(id=service.create_experiment(request).experiment_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="snapshotが見つかりません") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/experiments/{experiment_id}")
    def get_experiment(
        experiment_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            return record_dict(service.get_experiment(experiment_id))
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="experimentが見つかりません") from exc

    @app.get("/api/experiments")
    def list_experiments(
        _principal: Annotated[Principal, Depends(read)],
        snapshot_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ):
        return [
            record_dict(value)
            for value in service.list_experiments(snapshot_id=snapshot_id, limit=limit)
        ]

    @app.post("/api/runs", response_model=RunCreated, status_code=status.HTTP_202_ACCEPTED)
    def create_run(
        request: RunCreate,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            snapshot = service.create_run(request)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="experimentが見つかりません") from exc
        return RunCreated(run_id=snapshot.run_id, status=snapshot.status)

    @app.get("/api/runs", response_model=list[RunStatusOutput])
    def list_runs(
        _principal: Annotated[Principal, Depends(read)],
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        run_status: Annotated[str | None, Query(alias="status")] = None,
    ):
        try:
            return [
                _run_output(value)
                for value in service.list_runs(limit=limit, status=run_status)
            ]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}", response_model=RunStatusOutput)
    def get_run(
        run_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            return _run_output(service.get_run(run_id), resource_cost)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc

    @app.get("/api/runs/{run_id}/results")
    def get_results(
        run_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            return service.get_results(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc

    @app.post("/api/runs/{run_id}/cancel", response_model=RunStatusOutput)
    def cancel_run(
        run_id: str,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return _run_output(service.cancel(run_id), resource_cost)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc

    @app.post("/api/runs/{run_id}/resume", response_model=RunStatusOutput)
    def resume_run(
        run_id: str,
        request: ResumeInput,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return _run_output(
                service.resume(run_id, request.condition_fingerprint), resource_cost
            )
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc
        except ContractViolationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
