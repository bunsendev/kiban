from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from ..mapping_dry_run.catalog import MappingDryRunCatalog
from ..mapping_dry_run.evidence_schema import InvalidReportError
from .security import Permission, Principal


def install_mapping_dry_run_report_routes(
    app: FastAPI,
    authorize,
    catalog: MappingDryRunCatalog,
) -> None:
    read = authorize.require(Permission.READ)

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
