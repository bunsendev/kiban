"""HTTP boundary for the audited Pilot change application gate."""

import json

from fastapi import HTTPException, Request

from .change_applications import PortableChangeApplications
from .learning_reviews import LearningReviewConflict
from .pilot_evaluation_gates import PortablePilotEvaluationGates
from .production_handoff import ProductionHandoffError


def register_change_application_routes(app, paths, read_limited) -> None:
    service = PortableChangeApplications(paths.state / "shipment-actual-outcomes.sqlite3")
    evaluation_gates = PortablePilotEvaluationGates(paths)

    def require_legacy_path(application_id: str) -> None:
        if evaluation_gates.has_assessment_for_application(application_id):
            raise ProductionHandoffError(
                "Pilot評価Gate作成後は手順15-3から受入またはrollbackへ進んでください"
            )

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
            request,
            read_limited,
            128 * 1024,
            lambda payload: _legacy_transition(
                require_legacy_path,
                application_id,
                payload,
                service.evaluate_acceptance,
            ),
        )

    @app.post("/api/change-applications/{application_id}/rollback", status_code=201)
    async def evaluate_rollback(application_id: str, request: Request):
        return await _json_call(
            request,
            read_limited,
            64 * 1024,
            lambda payload: _legacy_transition(
                require_legacy_path,
                application_id,
                payload,
                service.evaluate_rollback,
            ),
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


def _legacy_transition(guard, application_id, payload, callback):
    guard(application_id)
    return callback(application_id, payload)
