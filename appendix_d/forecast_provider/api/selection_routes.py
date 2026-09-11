"""重要品目候補算出jobと確定選定版API。"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status

from ..selection import make_candidate_job, make_selection
from .schemas import Created
from .security import Permission, Principal, audit_payload
from .selection_schemas import CandidateJobCreate, SelectionCreate


def install_selection_routes(app: FastAPI, authorize, selection) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)
    approve = authorize.require(Permission.APPROVE)

    @app.post(
        "/api/selection-candidate-jobs",
        response_model=Created,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_candidate_job(
        request: CandidateJobCreate,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            value = make_candidate_job(audit_payload(request, principal, "requested_by"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            selection.put_candidate_job(value)
            return Created(id=value.candidate_job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="日次buildが見つかりません") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/selection-candidate-jobs")
    def list_candidate_jobs(
        _principal: Annotated[Principal, Depends(read)],
    ):
        return [value.__dict__ for value in selection.list_candidate_jobs()]

    @app.get("/api/selection-candidate-jobs/{candidate_job_id}")
    def get_candidate_job(
        candidate_job_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        value = selection.get_candidate_job(candidate_job_id)
        if value is None:
            raise HTTPException(status_code=404, detail="候補算出jobが見つかりません")
        return value.__dict__

    @app.get("/api/selection-candidate-jobs/{candidate_job_id}/candidates")
    def get_candidates(
        candidate_job_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        if selection.get_candidate_job(candidate_job_id) is None:
            raise HTTPException(status_code=404, detail="候補算出jobが見つかりません")
        return [value.__dict__ for value in selection.list_candidates(candidate_job_id)]

    @app.post("/api/selections", response_model=Created, status_code=201)
    def create_selection(
        request: SelectionCreate,
        principal: Annotated[Principal, Depends(approve)],
    ):
        try:
            value = make_selection(audit_payload(request, principal, "selected_by"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            saved = selection.put_selection(value)
            return Created(id=saved.selection_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="候補算出jobが見つかりません") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/selections")
    def list_selections(
        _principal: Annotated[Principal, Depends(read)],
    ):
        return [value.__dict__ for value in selection.list_selections()]

    @app.get("/api/selections/{selection_id}")
    def get_selection(
        selection_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        value = selection.get_selection(selection_id)
        if value is None:
            raise HTTPException(status_code=404, detail="選定版が見つかりません")
        return value.__dict__

    @app.get("/api/selections/{selection_id}/items")
    def get_selection_items(
        selection_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        if selection.get_selection(selection_id) is None:
            raise HTTPException(status_code=404, detail="選定版が見つかりません")
        return [value.__dict__ for value in selection.list_selection_items(selection_id)]
