"""HTTP boundary for Portable runtime candidate package issuance."""

import json

from fastapi import HTTPException, Request

from .candidate_packages import PortableCandidatePackages
from .production_handoff import ProductionHandoffError


def register_candidate_package_routes(app, paths, read_limited) -> None:
    service = PortableCandidatePackages(paths)

    @app.get("/api/runtime-candidate-packages")
    def list_candidate_packages():
        try:
            return service.overview()
        except ProductionHandoffError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/runtime-candidate-packages", status_code=201)
    async def issue_candidate_package(request: Request):
        try:
            raw = await read_limited(request, 64 * 1024)
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise ProductionHandoffError("入力内容を確認してください")
            return service.issue(payload)
        except (json.JSONDecodeError, ProductionHandoffError) as exc:
            raise HTTPException(422, str(exc)) from exc
