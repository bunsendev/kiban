"""Catalog/run API。学習・予測はHTTP request内で実行しない。"""

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..catalog import CatalogStore
from ..errors import ContractViolationError
from ..jobs.contracts import RunStore
from .acceptance_routes import install_acceptance_routes
from .daily_routes import install_daily_routes
from .evaluation_routes import install_evaluation_routes
from .ingestion_routes import install_ingestion_routes
from .master_routes import install_master_routes
from .normalization_routes import install_normalization_routes
from .schemas import (
    Created,
    ExperimentCreate,
    ResumeInput,
    RunCreate,
    RunCreated,
    RunStatusOutput,
    SnapshotCreate,
)
from .selection_routes import install_selection_routes
from .service import ApplicationService, NotFoundError, record_dict


def _output(value) -> RunStatusOutput:
    return RunStatusOutput(
        run_id=value.run_id,
        experiment_id=value.experiment_id,
        status=value.status,
        cancellation_requested=value.cancellation_requested,
        origin_counts=value.origin_counts,
        failure_count=value.failure_count,
    )


def create_app(
    store: RunStore,
    catalog: CatalogStore,
    api_token: str,
    snapshot_root: Path | None = None,
    ingestion=None,
    normalization=None,
    master=None,
    daily=None,
    acceptance=None,
    selection=None,
    evaluation_registry=None,
) -> FastAPI:
    if not api_token:
        raise ValueError("api_tokenは空にできません")
    app = FastAPI(title="Yosoku Kiban API", version="2.9")
    service = ApplicationService(store, catalog, snapshot_root)
    bearer = HTTPBearer(auto_error=False)

    def authorize(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        if credentials is None or not secrets.compare_digest(credentials.credentials, api_token):
            raise HTTPException(status_code=401, detail="認証が必要です")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    if ingestion is not None:
        install_ingestion_routes(app, authorize, ingestion)

    if normalization is not None:
        install_normalization_routes(app, authorize, normalization)

    if master is not None:
        install_master_routes(app, authorize, master)

    if daily is not None:
        install_daily_routes(app, authorize, daily)

    if acceptance is not None:
        install_acceptance_routes(app, authorize, acceptance)

    if selection is not None:
        install_selection_routes(app, authorize, selection)

    if evaluation_registry is not None:
        from ..evaluation_registry.service import EvaluationRegistryService

        install_evaluation_routes(
            app,
            authorize,
            EvaluationRegistryService(store, catalog, evaluation_registry, snapshot_root),
        )

    @app.post("/api/snapshots", response_model=Created, status_code=201)
    def create_snapshot(request: SnapshotCreate, _auth: None = Depends(authorize)):
        try:
            return Created(id=service.create_snapshot(request).snapshot_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: str, _auth: None = Depends(authorize)):
        try:
            return record_dict(service.get_snapshot(snapshot_id))
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="snapshotが見つかりません") from exc

    @app.post("/api/experiments", response_model=Created, status_code=201)
    def create_experiment(request: ExperimentCreate, _auth: None = Depends(authorize)):
        try:
            return Created(id=service.create_experiment(request).experiment_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="snapshotが見つかりません") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/experiments/{experiment_id}")
    def get_experiment(experiment_id: str, _auth: None = Depends(authorize)):
        try:
            return record_dict(service.get_experiment(experiment_id))
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="experimentが見つかりません") from exc

    @app.post("/api/runs", response_model=RunCreated, status_code=status.HTTP_202_ACCEPTED)
    def create_run(request: RunCreate, _auth: None = Depends(authorize)):
        try:
            snapshot = service.create_run(request)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="experimentが見つかりません") from exc
        return RunCreated(run_id=snapshot.run_id, status=snapshot.status)

    @app.get("/api/runs/{run_id}", response_model=RunStatusOutput)
    def get_run(run_id: str, _auth: None = Depends(authorize)):
        try:
            return _output(service.get_run(run_id))
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc

    @app.get("/api/runs/{run_id}/results")
    def get_results(run_id: str, _auth: None = Depends(authorize)):
        try:
            return service.get_results(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc

    @app.post("/api/runs/{run_id}/cancel", response_model=RunStatusOutput)
    def cancel_run(run_id: str, _auth: None = Depends(authorize)):
        try:
            return _output(service.cancel(run_id))
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc

    @app.post("/api/runs/{run_id}/resume", response_model=RunStatusOutput)
    def resume_run(run_id: str, request: ResumeInput, _auth: None = Depends(authorize)):
        try:
            return _output(service.resume(run_id, request.condition_fingerprint))
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc
        except ContractViolationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app
