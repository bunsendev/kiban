"""HTTP boundary for Pilot evaluation assessments and human decisions."""

import json

from fastapi import HTTPException, Request

from .learning_reviews import LearningReviewConflict
from .pilot_evaluation_gates import PortablePilotEvaluationGates
from .production_handoff import ProductionHandoffError


def register_pilot_evaluation_gate_routes(app, paths, read_limited) -> None:
    service = PortablePilotEvaluationGates(paths)

    @app.get("/api/pilot-evaluation-gates")
    def list_pilot_evaluation_gates():
        return service.overview()

    @app.post("/api/pilot-evaluation-gates", status_code=201)
    async def create_pilot_evaluation_gate(request: Request):
        return await _call(request, read_limited, service.create)

    @app.get("/api/pilot-evaluation-gates/{assessment_id}")
    def get_pilot_evaluation_gate(assessment_id: str):
        try:
            return service.view(assessment_id)
        except ProductionHandoffError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/pilot-evaluation-gates/{assessment_id}/decisions", status_code=201)
    async def decide_pilot_evaluation_gate(assessment_id: str, request: Request):
        return await _call(
            request, read_limited, lambda payload: service.decide(assessment_id, payload)
        )


async def _call(request, read_limited, callback):
    try:
        raw = await read_limited(request, 64 * 1024)
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            raise ProductionHandoffError("Pilot評価条件を確認してください")
        return callback(payload)
    except LearningReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (json.JSONDecodeError, ProductionHandoffError) as exc:
        raise HTTPException(422, str(exc)) from exc
