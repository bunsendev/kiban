"""Host、HTTPS、共通response headerのHTTP境界。"""

import uuid
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware


@dataclass(frozen=True)
class SecuritySettings:
    deployment_mode: str = "development"
    allowed_hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.deployment_mode not in {"development", "production"}:
            raise ValueError("deployment modeはdevelopmentまたはproductionです")
        if self.deployment_mode == "production" and not self.allowed_hosts:
            raise ValueError("productionではallowed hostsが必要です")
        if self.deployment_mode == "production" and "*" in self.allowed_hosts:
            raise ValueError("productionのallowed hostsに*は指定できません")

    @property
    def production(self) -> bool:
        return self.deployment_mode == "production"


def _apply_security_headers(
    response: Response,
    request_id: str,
    *,
    api_response: bool,
    production_https: bool,
) -> Response:
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if api_response:
        response.headers["Cache-Control"] = "no-store"
    if production_https:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


def install_security_boundary(app: FastAPI, settings: SecuritySettings) -> None:
    if settings.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware("http")
    async def security_boundary(request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        protected = request.url.path in {"/api", "/ui"} or request.url.path.startswith(
            ("/api/", "/ui/")
        )
        if settings.production and protected and request.url.scheme != "https":
            return _apply_security_headers(
                JSONResponse(
                    status_code=426,
                    content={
                        "detail": "production APIと管理画面はHTTPSが必要です",
                        "request_id": request_id,
                    },
                ),
                request_id,
                api_response=protected,
                production_https=False,
            )
        response = await call_next(request)
        return _apply_security_headers(
            response,
            request_id,
            api_response=request.url.path.startswith("/api"),
            production_https=settings.production and request.url.scheme == "https",
        )
