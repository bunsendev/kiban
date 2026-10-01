"""HTTP boundary for queuing a verified Portable build in the production ledger."""

import json

from fastapi import HTTPException, Request

from .production_handoff import PortableProductionHandoff, ProductionHandoffError


def register_production_handoff_routes(app, paths, read_limited) -> None:
    service = PortableProductionHandoff(paths)

    @app.get("/api/formal-forecast/{build_id}/production-run")
    def get_production_handoff(build_id: str):
        try:
            return service.view(build_id)
        except ProductionHandoffError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/formal-forecast/{build_id}/production-run", status_code=202)
    async def enqueue_production_handoff(build_id: str, request: Request):
        try:
            raw = await read_limited(request, 16 * 1024)
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise ProductionHandoffError("登録条件を確認してください")
            return service.enqueue(build_id, payload)
        except (json.JSONDecodeError, ProductionHandoffError) as exc:
            raise HTTPException(422, str(exc)) from exc
