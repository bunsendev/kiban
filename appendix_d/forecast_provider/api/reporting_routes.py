"""比較CSVと採用判断のBearer認証API。"""

from dataclasses import asdict

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse

from ..reporting import ReportingConflict, ReportingNotFound
from .reporting_schemas import AdoptionCreate, ReportExportCreate


def install_reporting_routes(app, authorize, service) -> None:
    @app.post("/api/comparisons/{comparison_id}/exports", status_code=201)
    def create_export(
        comparison_id: str,
        request: ReportExportCreate,
        _auth: None = Depends(authorize),
    ):
        try:
            return asdict(
                service.create_export(comparison_id, request.model_dump(mode="json"))
            )
        except ReportingNotFound as exc:
            raise HTTPException(status_code=404, detail="比較結果が見つかりません") from exc
        except ReportingConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/exports/{export_id}/metadata")
    def get_export_metadata(export_id: str, _auth: None = Depends(authorize)):
        try:
            return asdict(service.get_export(export_id))
        except ReportingNotFound as exc:
            raise HTTPException(status_code=404, detail="exportが見つかりません") from exc

    @app.get("/api/exports/{export_id}")
    def download_export(export_id: str, _auth: None = Depends(authorize)):
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
        comparison_id: str | None = None, _auth: None = Depends(authorize)
    ):
        return [asdict(value) for value in service.list_exports(comparison_id)]

    @app.post("/api/adoptions", status_code=201)
    def create_adoption(request: AdoptionCreate, _auth: None = Depends(authorize)):
        try:
            return asdict(service.create_adoption(request.model_dump(mode="json")))
        except ReportingNotFound as exc:
            raise HTTPException(status_code=404, detail="採用判断の参照先が見つかりません") from exc
        except ReportingConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/adoptions/{adoption_id}")
    def get_adoption(adoption_id: str, _auth: None = Depends(authorize)):
        try:
            return asdict(service.get_adoption(adoption_id))
        except ReportingNotFound as exc:
            raise HTTPException(status_code=404, detail="採用判断が見つかりません") from exc

    @app.get("/api/adoptions")
    def list_adoptions(
        comparison_id: str | None = None, _auth: None = Depends(authorize)
    ):
        return [asdict(value) for value in service.list_adoptions(comparison_id)]
