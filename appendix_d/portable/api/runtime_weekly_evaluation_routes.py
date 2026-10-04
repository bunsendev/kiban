"""HTTP boundary for immutable runtime-aware weekly evaluations."""

import json

from fastapi import HTTPException, Request

from .production_handoff import ProductionHandoffError
from .runtime_weekly_evaluations import PortableRuntimeWeeklyEvaluations


def register_runtime_weekly_evaluation_routes(app, paths, read_limited) -> None:
    service = PortableRuntimeWeeklyEvaluations(paths)

    @app.get("/api/runtime-weekly-evaluations")
    def list_runtime_weekly_evaluations():
        try:
            return service.overview()
        except ProductionHandoffError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/runtime-weekly-evaluations", status_code=201)
    async def create_runtime_weekly_evaluation(request: Request):
        try:
            raw = await read_limited(request, 32 * 1024)
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise ProductionHandoffError("Runtime週次評価条件を確認してください")
            return service.create(payload)
        except (json.JSONDecodeError, ProductionHandoffError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/runtime-weekly-evaluations/{evaluation_id}")
    def get_runtime_weekly_evaluation(evaluation_id: str):
        try:
            return service.view(evaluation_id)
        except ProductionHandoffError as exc:
            raise HTTPException(404, str(exc)) from exc
