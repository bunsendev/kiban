"""原本取込API route。"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status

from .schemas import Created, ImportCreate
from .security import Permission, Principal


def install_ingestion_routes(app: FastAPI, authorize, ingestion) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)
    @app.post("/api/imports", response_model=Created, status_code=status.HTTP_202_ACCEPTED)
    def create_import(
        request: ImportCreate,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        return Created(id=ingestion.enqueue(request.source_path).import_id)

    @app.get("/api/imports/{import_id}")
    def get_import(
        import_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        value = ingestion.get_job(import_id)
        if value is None:
            raise HTTPException(status_code=404, detail="importが見つかりません")
        return {
            **value.__dict__,
            "files": [item.__dict__ for item in ingestion.list_files(import_id)],
        }
