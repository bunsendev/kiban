"""HTTP boundary for evaluation-backed Pilot acceptance and rollback."""

import json

from fastapi import HTTPException, Request

from .learning_reviews import LearningReviewConflict
from .pilot_closeouts import PortablePilotCloseouts
from .production_handoff import ProductionHandoffError


def register_pilot_closeout_routes(app, paths, read_limited) -> None:
    service = PortablePilotCloseouts(paths)

    @app.get("/api/pilot-closeouts/{assessment_id}")
    def get_pilot_closeout(assessment_id: str):
        try:
            return service.view(assessment_id)
        except ProductionHandoffError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/pilot-closeouts/{assessment_id}/acceptance", status_code=201)
    async def accept_pilot(assessment_id: str, request: Request):
        return await _call(
            request,
            read_limited,
            lambda payload: service.accept(assessment_id, payload),
        )

    @app.post("/api/pilot-closeouts/{assessment_id}/rollback", status_code=201)
    async def rollback_pilot(assessment_id: str, request: Request):
        return await _call(
            request,
            read_limited,
            lambda payload: service.rollback(assessment_id, payload),
        )

    @app.post("/api/pilot-closeouts/{assessment_id}/pause", status_code=201)
    async def pause_pilot(assessment_id: str, request: Request):
        return await _call(
            request,
            read_limited,
            lambda payload: service.pause(assessment_id, payload),
        )


async def _call(request, read_limited, callback):
    try:
        raw = await read_limited(request, 128 * 1024)
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            raise ProductionHandoffError("Pilot完了確認を確認してください")
        return callback(payload)
    except LearningReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (json.JSONDecodeError, ProductionHandoffError) as exc:
        raise HTTPException(422, str(exc)) from exc
