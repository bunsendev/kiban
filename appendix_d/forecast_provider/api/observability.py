"""構造化HTTP監査log、運用指標、liveness/readiness。"""

import json
import logging
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from .authentication import Authorizer, Permission, Principal

ReadinessCheck = Callable[[], bool]


def _audit_logger() -> logging.Logger:
    logger = logging.getLogger("kiban.audit")
    logger.setLevel(logging.INFO)
    if not any(getattr(handler, "_kiban_audit", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._kiban_audit = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class OperationalMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._in_flight = 0
        self._requests: Counter[tuple[str, str, str]] = Counter()
        self._duration: Counter[tuple[str, str]] = Counter()

    def begin(self) -> None:
        with self._lock:
            self._in_flight += 1

    def finish(self, method: str, route: str, status_code: int, elapsed: float) -> None:
        status_class = f"{status_code // 100}xx"
        with self._lock:
            self._in_flight -= 1
            self._requests[(method, route, status_class)] += 1
            self._duration[(method, route)] += elapsed

    def render(self) -> str:
        with self._lock:
            in_flight = self._in_flight
            requests = self._requests.copy()
            durations = self._duration.copy()
            uptime = time.monotonic() - self._started_at
        lines = [
            "# HELP kiban_process_uptime_seconds Process uptime in seconds.",
            "# TYPE kiban_process_uptime_seconds gauge",
            f"kiban_process_uptime_seconds {uptime:.6f}",
            "# HELP kiban_http_requests_in_flight Current in-flight HTTP requests.",
            "# TYPE kiban_http_requests_in_flight gauge",
            f"kiban_http_requests_in_flight {in_flight}",
            "# HELP kiban_http_requests_total HTTP requests by method, route, and status class.",
            "# TYPE kiban_http_requests_total counter",
        ]
        for (method, route, status_class), count in sorted(requests.items()):
            labels = (
                f'method="{_escape_label(method)}",'
                f'route="{_escape_label(route)}",'
                f'status="{_escape_label(status_class)}"'
            )
            lines.append(f"kiban_http_requests_total{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP kiban_http_request_duration_seconds_sum Total HTTP request duration.",
                "# TYPE kiban_http_request_duration_seconds_sum counter",
            ]
        )
        for (method, route), duration in sorted(durations.items()):
            labels = f'method="{_escape_label(method)}",route="{_escape_label(route)}"'
            lines.append(f"kiban_http_request_duration_seconds_sum{{{labels}}} {duration:.6f}")
        return "\n".join(lines) + "\n"


def _route_name(request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "<unmatched>"


def _audit_record(request, status_code: int, elapsed: float) -> str:
    principal = getattr(request.state, "principal", None)
    route = _route_name(request)
    record = {
        "event": "http_request",
        "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "request_id": getattr(request.state, "request_id", None),
        "method": request.method,
        "route": route,
        "status": status_code,
        "duration_ms": round(elapsed * 1000, 3),
        "audit": bool(principal and request.method in {"POST", "PUT", "PATCH", "DELETE"}),
    }
    if isinstance(principal, Principal):
        record["subject"] = principal.subject
        record["roles"] = [role.value for role in principal.roles]
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def install_observability(
    app: FastAPI,
    authorize: Authorizer,
    readiness_checks: Mapping[str, ReadinessCheck] | None = None,
) -> OperationalMetrics:
    checks = dict(readiness_checks or {})
    metrics = OperationalMetrics()
    logger = _audit_logger()

    @app.middleware("http")
    async def observe_request(request, call_next):
        started = time.monotonic()
        status_code = 500
        metrics.begin()
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.monotonic() - started
            route = _route_name(request)
            metrics.finish(request.method, route, status_code, elapsed)
            logger.info(_audit_record(request, status_code, elapsed))

    @app.get("/ready", include_in_schema=False)
    def ready():
        results = {}
        for name, check in checks.items():
            try:
                results[name] = check() is True
            except Exception:
                results[name] = False
        ready_status = all(results.values())
        return JSONResponse(
            status_code=200 if ready_status else 503,
            content={"status": "ready" if ready_status else "not_ready", "checks": results},
        )

    read = authorize.require(Permission.READ)

    @app.get("/metrics", include_in_schema=False, response_class=PlainTextResponse)
    def get_metrics(_principal: Annotated[Principal, Depends(read)]) -> Response:
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    return metrics
