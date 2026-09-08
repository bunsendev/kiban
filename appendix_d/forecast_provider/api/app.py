"""最小run API。予測処理は呼び出さず、台帳操作だけを行う。"""

import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..errors import ContractViolationError
from ..jobs.contracts import RunStore
from .schemas import ResumeInput, RunCreate, RunCreated, RunStatusOutput
from .service import RunNotFoundError, RunService


def _output(snapshot) -> RunStatusOutput:
    return RunStatusOutput(
        run_id=snapshot.run_id,
        experiment_id=snapshot.experiment_id,
        status=snapshot.status,
        cancellation_requested=snapshot.cancellation_requested,
        origin_counts=snapshot.origin_counts,
        failure_count=snapshot.failure_count,
    )


def create_app(store: RunStore, api_token: str) -> FastAPI:
    if not api_token:
        raise ValueError("api_tokenは空にできません")
    app = FastAPI(title="Yosoku Kiban Run API", version="2.9")
    service = RunService(store)
    bearer = HTTPBearer(auto_error=False)

    def authorize(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        if credentials is None or not secrets.compare_digest(credentials.credentials, api_token):
            raise HTTPException(status_code=401, detail="認証が必要です")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/runs", response_model=RunCreated, status_code=status.HTTP_202_ACCEPTED)
    def create_run(request: RunCreate, _auth: None = Depends(authorize)):
        snapshot = service.create(request)
        return RunCreated(run_id=snapshot.run_id, status=snapshot.status)

    @app.get("/api/runs/{run_id}", response_model=RunStatusOutput)
    def get_run(run_id: str, _auth: None = Depends(authorize)):
        try:
            return _output(service.get(run_id))
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc

    @app.post("/api/runs/{run_id}/cancel", response_model=RunStatusOutput)
    def cancel_run(run_id: str, _auth: None = Depends(authorize)):
        try:
            return _output(service.cancel(run_id))
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc

    @app.post("/api/runs/{run_id}/resume", response_model=RunStatusOutput)
    def resume_run(run_id: str, request: ResumeInput, _auth: None = Depends(authorize)):
        try:
            return _output(service.resume(run_id, request.condition_fingerprint))
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="runが見つかりません") from exc
        except ContractViolationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app
