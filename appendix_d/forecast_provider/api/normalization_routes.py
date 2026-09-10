"""列mapping・出荷正規化・品質API route。"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status

from ..normalization import make_mapping
from .schemas import Created, MappingCreate, NormalizationCreate, SourceSelectionCreate
from .security import Permission, Principal, audit_payload


def install_normalization_routes(app: FastAPI, authorize, normalization) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)
    approve = authorize.require(Permission.APPROVE)
    @app.post("/api/mappings", response_model=Created, status_code=201)
    def create_mapping(
        request: MappingCreate,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            value = make_mapping(request.model_dump(exclude_none=True))
            normalization.put_mapping(value)
            return Created(id=value.mapping_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/mappings/{mapping_id}")
    def get_mapping(
        mapping_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        value = normalization.get_mapping(mapping_id)
        if value is None:
            raise HTTPException(status_code=404, detail="mappingが見つかりません")
        return value.__dict__

    @app.post("/api/source-selections", response_model=Created, status_code=201)
    def select_source(
        request: SourceSelectionCreate,
        principal: Annotated[Principal, Depends(approve)],
    ):
        try:
            value = normalization.select_source(**audit_payload(request, principal, "decided_by"))
            return Created(id=value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/source-selections")
    def list_source_selections(
        _principal: Annotated[Principal, Depends(read)],
        logical_path: str | None = None,
    ):
        return [value.__dict__ for value in normalization.list_selections(logical_path)]

    @app.post("/api/normalizations", response_model=Created, status_code=status.HTTP_202_ACCEPTED)
    def create_normalization(
        request: NormalizationCreate,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            value = normalization.enqueue(request.source_file_id, request.mapping_id)
            return Created(id=value.normalization_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/normalizations/{normalization_id}")
    def get_normalization(
        normalization_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        value = normalization.results(normalization_id)
        if value is None:
            raise HTTPException(status_code=404, detail="normalizationが見つかりません")
        return value

    @app.get("/api/quality")
    def get_quality(
        _principal: Annotated[Principal, Depends(read)],
    ):
        return normalization.quality()
