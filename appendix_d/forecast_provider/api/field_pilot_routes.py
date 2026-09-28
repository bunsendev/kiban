"""Field Pilot専用のloopback read APIと書き込み禁止境界。"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def install_field_pilot_routes(app: FastAPI, service) -> None:
    allowed_paths = {
        "/health", "/ready", "/ui/pilot", "/ui/pilot/", "/api/field-pilot/view",
        "/ui/assets/pilot.css", "/ui/assets/pilot.js",
    }

    @app.middleware("http")
    async def field_pilot_boundary(request: Request, call_next):
        path = request.url.path
        if request.url.hostname not in {"127.0.0.1", "localhost"}:
            return JSONResponse({"message": "現場PC内からのみ利用できます"}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            return JSONResponse({"message": "試験運用は読み取り専用です"}, status_code=405)
        if path not in allowed_paths:
            return JSONResponse({"message": "現場Pilotでは利用できません"}, status_code=404)
        return await call_next(request)

    @app.get("/api/field-pilot/view", include_in_schema=False)
    def pilot_view(request: Request):
        request.state.audit_operation = "FIELD_PILOT_SHADOW_VIEW"
        return service.view()
