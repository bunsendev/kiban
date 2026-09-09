"""原本取込API route。"""

from fastapi import Depends, FastAPI, HTTPException, status

from .schemas import Created, ImportCreate


def install_ingestion_routes(app: FastAPI, authorize, ingestion) -> None:
    @app.post("/api/imports", response_model=Created, status_code=status.HTTP_202_ACCEPTED)
    def create_import(request: ImportCreate, _auth: None = Depends(authorize)):
        return Created(id=ingestion.enqueue(request.source_path).import_id)

    @app.get("/api/imports/{import_id}")
    def get_import(import_id: str, _auth: None = Depends(authorize)):
        value = ingestion.get_job(import_id)
        if value is None:
            raise HTTPException(status_code=404, detail="importが見つかりません")
        return {
            **value.__dict__,
            "files": [item.__dict__ for item in ingestion.list_files(import_id)],
        }
