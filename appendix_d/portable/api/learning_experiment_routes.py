"""HTTP boundary for SHADOW learning experiment plans and runs."""

import json

from fastapi import HTTPException, Request, Response

from .learning_experiments import PortableLearningExperiments
from .learning_reviews import LearningReviewConflict
from .production_handoff import ProductionHandoffError


def register_learning_experiment_routes(app, paths, read_limited) -> None:
    service = PortableLearningExperiments(paths.state / "shipment-actual-outcomes.sqlite3")

    @app.get("/api/learning-experiments")
    def list_learning_experiments():
        return service.overview()

    @app.post("/api/learning-experiments/plans", status_code=201)
    async def create_learning_experiment_plan(request: Request):
        return await _json_call(request, read_limited, 32 * 1024, service.create_plan)

    @app.get("/api/learning-experiments/plans/{plan_id}")
    def get_learning_experiment_plan(plan_id: str):
        try:
            return service.view_plan(plan_id)
        except ProductionHandoffError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/learning-experiments/plans/{plan_id}/template")
    def get_learning_experiment_template(plan_id: str):
        try:
            return Response(
                service.template(plan_id), media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="challenger-results.csv"'},
            )
        except ProductionHandoffError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/learning-experiments/plans/{plan_id}/runs", status_code=201)
    async def create_learning_experiment_run(plan_id: str, request: Request):
        return await _json_call(
            request, read_limited, 3 * 1024 * 1024,
            lambda payload: service.create_run(plan_id, payload),
        )

    @app.post("/api/learning-experiments/runs/{run_id}/decision", status_code=201)
    async def decide_learning_experiment(run_id: str, request: Request):
        try:
            return await _json_call(
                request, read_limited, 16 * 1024,
                lambda payload: service.decide(run_id, payload),
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
