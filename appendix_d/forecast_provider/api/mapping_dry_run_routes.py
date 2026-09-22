from fastapi import FastAPI

from ..mapping_dry_run.catalog import MappingDryRunCatalog
from .inventory_normalization_routes import install_inventory_normalization_routes
from .mapping_dry_run_job_routes import install_mapping_dry_run_job_routes
from .mapping_dry_run_report_routes import install_mapping_dry_run_report_routes
from .mapping_dry_run_source_routes import install_mapping_dry_run_source_routes


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
    """Install intake routes while keeping each business capability isolated."""

    install_mapping_dry_run_report_routes(app, authorize, catalog)
    install_mapping_dry_run_source_routes(
        app,
        authorize,
        sources=sources,
        uploader=uploader,
        bulk_uploader=bulk_uploader,
        inventory_profiler=inventory_profiler,
        product_bridge=product_bridge,
        inventory_preview=inventory_preview,
    )
    install_inventory_normalization_routes(
        app,
        authorize,
        inventory_normalization,
    )
    install_mapping_dry_run_job_routes(
        app,
        authorize,
        jobs=jobs,
        mappings=mappings,
        sources=sources,
    )
