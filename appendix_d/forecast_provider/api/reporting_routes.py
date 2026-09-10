"""比較CSVと採用判断のBearer認証API。"""

from dataclasses import asdict
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse

from ..reporting import ReportingConflict, ReportingNotFound
from .reporting_schemas import AdoptionCreate, ReportExportCreate
from .security import Permission, Principal, audit_payload


def install_reporting_routes(app, authorize, service) -> None:
    read = authorize.require(Permission.READ)
    approve = authorize.require(Permission.APPROVE)
    export = authorize.require(Permission.EXPORT)
    @app.get("/api/comparisons/{comparison_id}/adoption-context")
    def get_adoption_context(
        comparison_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            return service.adoption_context(comparison_id)
        except ReportingNotFound as exc:
            raise HTTPException(status_code=404, detail="比較結果が見つかりません") from exc
        except ReportingConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/comparisons/{comparison_id}/exports", status_code=201)
    def create_export(
        comparison_id: str,
        request: ReportExportCreate,
        principal: Annotated[Principal, Depends(export)],
    ):
        try:
            return asdict(
                service.create_export(
                    comparison_id,
                    audit_payload(request, principal, "requested_by"),
                )
            )
        except ReportingNotFound as exc:
            raise HTTPException(status_code=404, detail="比較結果が見つかりません") from exc
        except ReportingConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/exports/{export_id}/metadata")
    def get_export_metadata(
        export_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            return asdict(service.get_export(export_id))
        except ReportingNotFound as exc:
            raise HTTPException(status_code=404, detail="exportが見つかりません") from exc

    @app.get("/api/exports/{export_id}")
    def download_export(
        export_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            record, path = service.export_path(export_id)
        except ReportingNotFound as exc:
            raise HTTPException(status_code=404, detail="exportが見つかりません") from exc
        except ReportingConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FileResponse(
            path,
            media_type="text/csv; charset=utf-8",
            filename=f"comparison-{record.comparison_id}.csv",
            headers={"X-Content-SHA256": record.output_sha256},
        )

    @app.get("/api/exports")
    def list_exports(
        _principal: Annotated[Principal, Depends(read)],
        comparison_id: str | None = None,
    ):
        return [asdict(value) for value in service.list_exports(comparison_id)]

    @app.post("/api/adoptions", status_code=201)
    def create_adoption(
        request: AdoptionCreate,
        principal: Annotated[Principal, Depends(approve)],
    ):
        try:
            return asdict(
                service.create_adoption(audit_payload(request, principal, "decided_by"))
            )
        except ReportingNotFound as exc:
            raise HTTPException(status_code=404, detail="採用判断の参照先が見つかりません") from exc
        except ReportingConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/adoptions/{adoption_id}")
    def get_adoption(
        adoption_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            return asdict(service.get_adoption(adoption_id))
        except ReportingNotFound as exc:
            raise HTTPException(status_code=404, detail="採用判断が見つかりません") from exc

    @app.get("/api/adoptions")
    def list_adoptions(
        _principal: Annotated[Principal, Depends(read)],
        comparison_id: str | None = None,
    ):
        return [asdict(value) for value in service.list_adoptions(comparison_id)]
