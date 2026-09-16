"""API全体で共有する、機密値を含まないエラー応答。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    426: "HTTPS_REQUIRED",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def error_payload(
    request: Request,
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    details: Any = None,
) -> dict[str, Any]:
    return {
        "code": code or STATUS_CODES.get(status_code, "HTTP_ERROR"),
        "message": message,
        "details": {} if details is None else details,
        "request_id": getattr(request.state, "request_id", None),
    }


def error_response(
    request: Request,
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response_headers = dict(headers or {})
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response_headers["X-Request-ID"] = request_id
    if request.url.path == "/api" or request.url.path.startswith("/api/"):
        response_headers["Cache-Control"] = "no-store"
    return JSONResponse(
        status_code=status_code,
        content=error_payload(request, status_code, message, code=code, details=details),
        headers=response_headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        message = detail if isinstance(detail, str) else "要求を処理できません"
        details = {} if isinstance(detail, str) else detail
        return error_response(
            request,
            exc.status_code,
            message,
            details=details,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        issues = [
            {
                "location": [str(value) for value in issue.get("loc", ())],
                "type": issue.get("type", "validation_error"),
                "message": issue.get("msg", "入力値が不正です"),
            }
            for issue in exc.errors()
        ]
        return error_response(
            request,
            422,
            "入力値を確認してください",
            code="REQUEST_VALIDATION_FAILED",
            details={"issues": issues},
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, _exc: Exception):
        return error_response(
            request,
            500,
            "サーバー内部でエラーが発生しました",
            code="INTERNAL_ERROR",
        )
