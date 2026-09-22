"""Catalog/run API。学習・予測はHTTP request内で実行しない。"""

from collections.abc import Callable, Mapping
from pathlib import Path

from fastapi import FastAPI

from ..catalog import CatalogStore
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
from .core_routes import install_core_routes
from .daily_routes import install_daily_routes
from .error_responses import install_error_handlers
from .evaluation_routes import install_evaluation_routes
from .idempotency import IdempotencyStore, InMemoryIdempotencyStore, idempotent_route_class
from .ingestion_routes import install_ingestion_routes
from .lifecycle_routes import install_lifecycle_routes
from .mapping_dry_run_routes import install_mapping_dry_run_routes
from .master_routes import install_master_routes
from .model_review_action_routes import install_model_review_action_routes
from .model_review_retest_routes import install_model_review_retest_routes
from .model_review_routes import install_model_review_routes
from .normalization_routes import install_normalization_routes
from .observability import install_observability
from .oidc_login import OidcLoginSettings, install_oidc_login_routes
from .reporting_routes import install_reporting_routes
from .resource_cost_routes import install_resource_cost_routes
from .security import (
    Authenticator,
    Authorizer,
    SecuritySettings,
    TokenAuthenticator,
    install_security_boundary,
)
from .selection_routes import install_selection_routes
from .service import ApplicationService
from .worker_status_routes import install_worker_status_routes


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
    review_actions=None,
    review_retests=None,
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
    install_core_routes(app, authorize, service, resource_cost)

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
                    if review_actions is not None:
                        from ..model_review import ReviewActionService

                        install_model_review_action_routes(
                            app,
                            authorize,
                            ReviewActionService(model_reviews, review_actions),
                        )
                        if review_retests is not None:
                            from ..model_review import ReviewRetestService

                            install_model_review_retest_routes(
                                app,
                                authorize,
                                ReviewRetestService(
                                    model_reviews,
                                    review_actions,
                                    review_retests,
                                    campaign_service,
                                ),
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

    return app
