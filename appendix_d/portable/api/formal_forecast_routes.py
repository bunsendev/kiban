"""HTTP boundary for the Portable formal shipment and forecast pipeline."""

from __future__ import annotations

import json

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from .formal_forecast_pipeline import (
    FormalForecastError,
    PortableFormalForecastPipeline,
    translate_error,
)


def register_formal_forecast_routes(app, paths, read_limited) -> None:
    service = PortableFormalForecastPipeline(paths)

    @app.get("/api/formal-inventory/pipeline/{registration_id}/forecast")
    def get_formal_forecast(registration_id: str):
        try:
            return service.view(registration_id)
        except Exception as exc:
            error = translate_error(exc)
            raise HTTPException(404, str(error)) from exc

    @app.post("/api/formal-inventory/pipeline/{registration_id}/forecast", status_code=201)
    async def run_formal_forecast(registration_id: str, request: Request):
        try:
            raw = await read_limited(request, 16 * 1024)
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise FormalForecastError("予測開始条件を確認してください")
            return service.run(registration_id, payload)
        except (json.JSONDecodeError, FormalForecastError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            error = translate_error(exc)
            raise HTTPException(422, str(error)) from exc

    @app.get("/api/formal-forecast/{build_id}/download")
    def download_formal_forecast(build_id: str):
        try:
            path = service.result_path(build_id)
        except FormalForecastError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(
            path,
            filename=f"bunsen-formal-forecast-{build_id}.json",
            media_type="application/json",
        )
