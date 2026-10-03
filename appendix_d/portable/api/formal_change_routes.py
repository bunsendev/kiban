"""HTTP boundary for formal change proposal drafting and approval."""

import json

from fastapi import HTTPException, Request

from .formal_changes import PortableFormalChanges
from .learning_reviews import LearningReviewConflict
from .production_handoff import ProductionHandoffError


def register_formal_change_routes(app, paths, read_limited) -> None:
    service = PortableFormalChanges(paths.state / "shipment-actual-outcomes.sqlite3")

    @app.get("/api/formal-changes")
    def list_formal_changes():
        return service.overview()

    @app.post("/api/formal-changes", status_code=201)
    async def create_formal_change(request: Request):
        return await _json_call(request, read_limited, 160 * 1024, service.create_proposal)

    @app.get("/api/formal-changes/{proposal_id}")
    def get_formal_change(proposal_id: str):
        try:
            return service.view_proposal(proposal_id)
        except ProductionHandoffError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/formal-changes/{proposal_id}/decision", status_code=201)
    async def decide_formal_change(proposal_id: str, request: Request):
        try:
            return await _json_call(
                request, read_limited, 16 * 1024,
                lambda payload: service.decide(proposal_id, payload),
            )
        except LearningReviewConflict as exc:
            raise HTTPException(409, str(exc)) from exc


async def _json_call(request, read_limited, limit, callback):
    try:
        raw = await read_limited(request, limit)
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            raise ProductionHandoffError("入力内容を確認してください")
        return callback(payload)
    except LearningReviewConflict:
        raise
    except (json.JSONDecodeError, ProductionHandoffError) as exc:
        raise HTTPException(422, str(exc)) from exc
