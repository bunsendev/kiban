"""Catalog/run API。学習・予測はHTTP request内で実行しない。"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status

from ..catalog import CatalogStore
from ..errors import ContractViolationError
from ..jobs.contracts import RunStore
from ..mapping_dry_run.bulk_uploads import MappingDryRunBulkUploader
from ..mapping_dry_run.catalog import MappingDryRunCatalog
from ..mapping_dry_run.inventory_normalization_preview import InventoryNormalizationPreview
from ..mapping_dry_run.inventory_profiles import InventoryStructureProfiler
from ..mapping_dry_run.product_bridge import ProductBridgeService
from ..mapping_dry_run.sources import MappingDryRunSourceCatalog
from ..mapping_dry_run.uploads import MappingDryRunSourceUploader
from ..ui import install_ui_routes
from .acceptance_routes import install_acceptance_routes
from .campaign_routes import install_campaign_routes
from .conformance_job_routes import install_conformance_job_routes
from .daily_routes import install_daily_routes
from .error_responses import install_error_handlers
from .evaluation_routes import install_evaluation_routes
from .idempotency import IdempotencyStore, InMemoryIdempotencyStore, idempotent_route_class
from .ingestion_routes import install_ingestion_routes
from .lifecycle_routes import install_lifecycle_routes
from .mapping_dry_run_routes import install_mapping_dry_run_routes
from .master_routes import install_master_routes
from .model_review_routes import install_model_review_routes
from .normalization_routes import install_normalization_routes
from .observability import install_observability
from .oidc_login import OidcLoginSettings, install_oidc_login_routes
from .reporting_routes import install_reporting_routes
from .resource_cost_routes import install_resource_cost_routes
from .schemas import (
    Created,
    ExperimentCreate,
    ResumeInput,
    RunCreate,
    RunCreated,
    RunStatusOutput,
    SnapshotCreate,
)
from .security import (
    Authenticator,
    Authorizer,
    Permission,
    Principal,
    SecuritySettings,
    TokenAuthenticator,
    install_security_boundary,
)
from .selection_routes import install_selection_routes
from .service import ApplicationService, NotFoundError, record_dict
from .worker_status_routes import install_worker_status_routes


def _output(value, resource_cost=None) -> RunStatusOutput:
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


def create_app(
    store: RunStore,
    catalog: CatalogStore,
    api_token: str | Authenticator,
    snapshot_root: Path | None = None,
    ingestion=None,
    normalization=None,
    master=None,
    daily=None,
    acceptance=None,
    selection=None,
    evaluation_registry=None,
    reporting=None,
    report_root: Path | None = None,
    security_settings: SecuritySettings | None = None,
    legacy_subject: str = "local-admin",
    readiness_checks: Mapping[str, Callable[[], bool]] | None = None,
    lifecycle=None,
    oidc_login_settings: OidcLoginSettings | None = None,
    mapping_dry_run_root: Path | None = None,
    mapping_dry_run_jobs=None,
    mapping_dry_run_input_root: Path | None = None,
    inventory_normalization=None,
    idempotency_store: IdempotencyStore | None = None,
    resource_cost=None,
    worker_status=None,
    worker_stale_seconds: float = 45,
    conformance_jobs=None,
    comparison_campaigns=None,
    model_reviews=None,
) -> FastAPI:
    if isinstance(api_token, str) and not api_token:
        raise ValueError("api_tokenは空にできません")
    settings = security_settings or SecuritySettings()
    authenticator = (
        TokenAuthenticator.single(api_token, legacy_subject)
        if isinstance(api_token, str)
        else api_token
    )
    if settings.production and not authenticator.production_ready:
        raise ValueError("productionでは複数credential設定を使用してください")
    app = FastAPI(
        title="Yosoku Kiban API",
        version="2.9",
        docs_url=None if settings.production else "/docs",
        redoc_url=None if settings.production else "/redoc",
        openapi_url=None if settings.production else "/openapi.json",
    )
    app.router.route_class = idempotent_route_class(
        idempotency_store or InMemoryIdempotencyStore()
    )
    install_error_handlers(app)
    install_security_boundary(app, settings)
    install_ui_routes(app)
    install_oidc_login_routes(app, oidc_login_settings)
    service = ApplicationService(store, catalog, snapshot_root)
    authorize = Authorizer(authenticator)
    checks = dict(readiness_checks or {})
    if "authentication" in checks:
        raise ValueError("authentication readiness check名は予約済みです")
    checks["authentication"] = authenticator.readiness
    install_observability(app, authorize, checks)
    if resource_cost is not None:
        install_resource_cost_routes(app, authorize, resource_cost)
    from ..worker_status import WorkerStatusService

    install_worker_status_routes(
        app,
        authorize,
        WorkerStatusService(store, worker_status, stale_seconds=worker_stale_seconds),
    )
    install_mapping_dry_run_routes(
        app,
        authorize,
        MappingDryRunCatalog(mapping_dry_run_root),
        mapping_dry_run_jobs,
        normalization,
        MappingDryRunSourceCatalog(mapping_dry_run_input_root),
        MappingDryRunSourceUploader(mapping_dry_run_input_root),
        MappingDryRunBulkUploader(mapping_dry_run_input_root),
        InventoryStructureProfiler(mapping_dry_run_input_root),
        ProductBridgeService(mapping_dry_run_input_root),
        InventoryNormalizationPreview(mapping_dry_run_input_root),
        inventory_normalization,
    )
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

        evaluation_service = EvaluationRegistryService(
            store,
            catalog,
            evaluation_registry,
            snapshot_root,
            resource_cost,
        )
        install_evaluation_routes(
            app,
            authorize,
            evaluation_service,
        )
        if conformance_jobs is not None:
            from ..provider_conformance.service import ConformanceJobService
            from .campaign_service import ComparisonCampaignService

            conformance_service = ConformanceJobService(catalog, conformance_jobs)
            install_conformance_job_routes(
                app,
                authorize,
                conformance_service,
            )
            if comparison_campaigns is not None:
                campaign_service = ComparisonCampaignService(
                    comparison_campaigns,
                    service,
                    conformance_service,
                    evaluation_service,
                )
                install_campaign_routes(
                    app,
                    authorize,
                    campaign_service,
                )
                if model_reviews is not None:
                    from ..model_review import ModelDriftReviewService

                    install_model_review_routes(
                        app,
                        authorize,
                        ModelDriftReviewService(model_reviews, campaign_service),
                    )

    if reporting is not None:
        if evaluation_registry is None or acceptance is None or report_root is None:
            raise ValueError("reportingには評価台帳、受入台帳、report rootが必要です")
        from ..reporting import ReportingService

        install_reporting_routes(
            app,
            authorize,
            ReportingService(
                evaluation_registry,
                catalog,
                acceptance,
                reporting,
                report_root,
                snapshot_root,
                resource_cost,
            ),
        )

    if lifecycle is not None:
        if evaluation_registry is None or reporting is None:
            raise ValueError("lifecycleには評価台帳と採用台帳が必要です")
        from ..lifecycle import LifecycleService, TrialLifecycleService

        lifecycle_service = LifecycleService(
            store, catalog, evaluation_registry, reporting, lifecycle
        )
        trial_service = TrialLifecycleService(store, catalog, evaluation_registry, lifecycle)
        install_lifecycle_routes(app, authorize, lifecycle_service, trial_service)

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
                _output(value)
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
            return _output(service.get_run(run_id), resource_cost)
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
            return _output(service.cancel(run_id), resource_cost)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc

    @app.post("/api/runs/{run_id}/resume", response_model=RunStatusOutput)
    def resume_run(
        run_id: str,
        request: ResumeInput,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return _output(
                service.resume(run_id, request.condition_fingerprint), resource_cost
            )
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc
        except ContractViolationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app
