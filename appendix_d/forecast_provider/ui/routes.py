"""同一originで管理画面の静的assetを安全に配信する。"""

from pathlib import Path

from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

STATIC_ROOT = Path(__file__).with_name("static")
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class SecureStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.update(SECURITY_HEADERS)
        return response


def install_ui_routes(app) -> None:
    app.mount(
        "/ui/assets",
        SecureStaticFiles(directory=STATIC_ROOT),
        name="management-ui-assets",
    )

    @app.get("/ui", include_in_schema=False)
    @app.get("/ui/", include_in_schema=False)
    def management_ui():
        return FileResponse(
            STATIC_ROOT / "index.html",
            media_type="text/html; charset=utf-8",
            headers=SECURITY_HEADERS,
        )

    @app.get("/ui/lifecycle", include_in_schema=False)
    @app.get("/ui/lifecycle/", include_in_schema=False)
    def lifecycle_ui():
        return FileResponse(
            STATIC_ROOT / "lifecycle.html",
            media_type="text/html; charset=utf-8",
            headers=SECURITY_HEADERS,
        )

    @app.get("/ui/readiness", include_in_schema=False)
    @app.get("/ui/readiness/", include_in_schema=False)
    def readiness_ui():
        return FileResponse(
            STATIC_ROOT / "readiness.html",
            media_type="text/html; charset=utf-8",
            headers=SECURITY_HEADERS,
        )

    @app.get("/ui/selection", include_in_schema=False)
    @app.get("/ui/selection/", include_in_schema=False)
    def selection_ui():
        return FileResponse(
            STATIC_ROOT / "selection.html",
            media_type="text/html; charset=utf-8",
            headers=SECURITY_HEADERS,
        )

    @app.get("/ui/acceptance", include_in_schema=False)
    @app.get("/ui/acceptance/", include_in_schema=False)
    def acceptance_ui():
        return FileResponse(
            STATIC_ROOT / "acceptance.html",
            media_type="text/html; charset=utf-8",
            headers=SECURITY_HEADERS,
        )

    @app.get("/ui/intake", include_in_schema=False)
    @app.get("/ui/intake/", include_in_schema=False)
    def intake_ui():
        return FileResponse(
            STATIC_ROOT / "intake.html",
            media_type="text/html; charset=utf-8",
            headers=SECURITY_HEADERS,
        )

    @app.get("/ui/matching", include_in_schema=False)
    @app.get("/ui/matching/", include_in_schema=False)
    def matching_ui():
        return FileResponse(
            STATIC_ROOT / "matching.html",
            media_type="text/html; charset=utf-8",
            headers=SECURITY_HEADERS,
        )
