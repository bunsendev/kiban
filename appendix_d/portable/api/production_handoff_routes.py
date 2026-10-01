"""HTTP boundary for queuing a verified Portable build in the production ledger."""

import json

from fastapi import HTTPException, Request

from .production_handoff import PortableProductionHandoff, ProductionHandoffError
from .production_projection import PortableProductionProjection
from .production_worker import PortableProductionWorker


def register_production_handoff_routes(app, paths, read_limited) -> None:
    service = PortableProductionHandoff(paths)
    projection = PortableProductionProjection(paths, service)
    worker = PortableProductionWorker(
        service.database,
        paths.formal_forecast / "ProductionArtifacts",
        paths.state / "ProductionWork",
    )
    for status in ("QUEUED", "RUNNING"):
        for run in service.service.runs.list_runs(limit=200, status=status):
            worker.submit(run.run_id)

    def current(build_id: str) -> dict:
        view = service.view(build_id)
        handoff = view.get("handoff")
        if handoff is not None:
            handoff["worker_error"] = worker.error(handoff["run_id"])
        return view

    @app.get("/api/formal-forecast/{build_id}/production-run")
    def get_production_handoff(build_id: str):
        try:
            return current(build_id)
        except ProductionHandoffError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/formal-forecast/{build_id}/production-run", status_code=202)
    async def enqueue_production_handoff(build_id: str, request: Request):
        try:
            raw = await read_limited(request, 16 * 1024)
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise ProductionHandoffError("登録条件を確認してください")
            result = service.enqueue(build_id, payload)
            worker.submit(result["run_id"])
            return current(build_id)["handoff"]
        except (json.JSONDecodeError, ProductionHandoffError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/formal-forecast/{build_id}/production-run/resume", status_code=202)
    def resume_production_handoff(build_id: str):
        try:
            worker.submit(service.run_id(build_id))
            return current(build_id)["handoff"]
        except ProductionHandoffError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/formal-forecast/{build_id}/production-projection")
    def get_production_projection(build_id: str):
        try:
            return projection.projection(build_id)
        except ProductionHandoffError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/formal-forecast/{build_id}/daily-summary", status_code=201)
    async def create_daily_summary(build_id: str, request: Request):
        try:
            raw = await read_limited(request, 16 * 1024)
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise ProductionHandoffError("日次業務サマリーの確認条件を確認してください")
            return projection.daily_summary(build_id, payload)
        except (json.JSONDecodeError, ProductionHandoffError) as exc:
            raise HTTPException(422, str(exc)) from exc
