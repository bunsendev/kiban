"""HTTP boundary for the audited Pilot change application gate."""

import json

from fastapi import HTTPException, Request

from .change_applications import PortableChangeApplications
from .learning_reviews import LearningReviewConflict
from .production_handoff import ProductionHandoffError


def register_change_application_routes(app, paths, read_limited) -> None:
    service = PortableChangeApplications(paths.state / "shipment-actual-outcomes.sqlite3")

    @app.get("/api/change-applications")
    def list_change_applications():
        return service.overview()

    @app.post("/api/change-applications", status_code=201)
    async def create_change_application(request: Request):
        return await _json_call(request, read_limited, 64 * 1024, service.create_application)

    @app.get("/api/change-applications/{application_id}")
    def get_change_application(application_id: str):
        try:
            return service.view_application(application_id)
        except ProductionHandoffError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/change-applications/{application_id}/pilot-gate", status_code=201)
    async def evaluate_pilot_gate(application_id: str, request: Request):
        return await _json_call(
            request, read_limited, 64 * 1024,
            lambda payload: service.evaluate_gate(application_id, payload),
        )

    @app.post("/api/change-applications/{application_id}/acceptance", status_code=201)
    async def evaluate_acceptance(application_id: str, request: Request):
        return await _json_call(
            request, read_limited, 128 * 1024,
            lambda payload: service.evaluate_acceptance(application_id, payload),
        )

    @app.post("/api/change-applications/{application_id}/rollback", status_code=201)
    async def evaluate_rollback(application_id: str, request: Request):
        return await _json_call(
            request, read_limited, 64 * 1024,
            lambda payload: service.evaluate_rollback(application_id, payload),
        )


async def _json_call(request, read_limited, limit, callback):
    try:
        raw = await read_limited(request, limit)
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            raise ProductionHandoffError("入力内容を確認してください")
        return callback(payload)
    except LearningReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (json.JSONDecodeError, ProductionHandoffError) as exc:
        raise HTTPException(422, str(exc)) from exc
