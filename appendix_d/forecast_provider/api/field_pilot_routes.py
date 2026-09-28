"""Field Pilot専用のloopback Shadow境界と限定された学習メタデータ操作。"""

import hmac
import re
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

LEARNING_ACTION = re.compile(r"^/api/field-pilot/learning/[0-9a-f]{64}/(confirm|disagree)$")
ADMIN_ACTION = re.compile(
    r"^/api/field-pilot/admin/(approve|reject)/[0-9a-f]{64}$"
    r"|^/api/field-pilot/admin/deactivate/learned-[0-9a-f]{24}$"
)


class OperatorDecision(BaseModel):
    kind: str


class AdminDecision(BaseModel):
    kind: str
    actor: str
    date_column: str | None = None
    date_format: str | None = None
    quantity_column: str | None = None
    location_column: str | None = None
    jan_column: str | None = None
    expiry_column: str | None = None
    source_unit: str | None = None
    normalized_unit: str | None = None
    location_id: str | None = None
    mapping_version: str | None = None


def install_field_pilot_routes(app: FastAPI, service) -> None:
    allowed_paths = {
        "/health", "/ready", "/ui/pilot", "/ui/pilot/", "/api/field-pilot/view",
        "/api/field-pilot/inbox",
        "/api/field-pilot/learning", "/api/field-pilot/admin",
        "/ui/pilot/admin", "/ui/pilot/admin/",
        "/ui/assets/pilot.css", "/ui/assets/pilot.js",
        "/ui/assets/pilot_admin.js",
    }

    @app.middleware("http")
    async def field_pilot_boundary(request: Request, call_next):
        path = request.url.path
        if request.url.hostname not in {"127.0.0.1", "localhost"}:
            return JSONResponse({"message": "現場PC内からのみ利用できます"}, status_code=403)
        if path == "/api/field-pilot/admin" or ADMIN_ACTION.fullmatch(path):
            configured = service.learning_admin_token
            supplied = request.headers.get("x-field-pilot-admin-token", "")
            if not (configured and supplied) or not hmac.compare_digest(configured, supplied):
                return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        if request.method == "POST":
            if not (LEARNING_ACTION.fullmatch(path) or ADMIN_ACTION.fullmatch(path)):
                return JSONResponse({"message": "試験運用は読み取り専用です"}, status_code=405)
            if not request.headers.get("content-type", "").startswith("application/json"):
                return JSONResponse({"message": "要求形式を確認してください"}, status_code=415)
            origin = request.headers.get("origin")
            if origin and origin != f"http://{request.headers.get('host')}":
                return JSONResponse({"message": "現場PC内からのみ利用できます"}, status_code=403)
            return await call_next(request)
        if request.method not in {"GET", "HEAD"}:
            return JSONResponse({"message": "試験運用は読み取り専用です"}, status_code=405)
        if path not in allowed_paths:
            return JSONResponse({"message": "現場Pilotでは利用できません"}, status_code=404)
        return await call_next(request)

    @app.get("/api/field-pilot/view", include_in_schema=False)
    def pilot_view(request: Request):
        request.state.audit_operation = "FIELD_PILOT_SHADOW_VIEW"
        return service.view()

    @app.get("/api/field-pilot/inbox", include_in_schema=False)
    def pilot_inbox(request: Request):
        request.state.audit_operation = "FIELD_PILOT_INBOX_VIEW"
        return service.inbox_view()

    @app.get("/api/field-pilot/learning", include_in_schema=False)
    def learning_view(request: Request):
        request.state.audit_operation = "FIELD_PILOT_LEARNING_VIEW"
        return service.learning_view()

    @app.post("/api/field-pilot/learning/{candidate_id}/confirm", include_in_schema=False)
    def operator_confirm(candidate_id: str, decision: OperatorDecision, request: Request):
        request.state.audit_operation = "FIELD_PILOT_LEARNING_CONFIRM"
        try:
            return service.learning.operator_decide(
                candidate_id, decision.kind, actor=service.learning_operator_id,
            )
        except (AttributeError, ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse({"message": "管理担当者へご確認ください"}, status_code=409)

    @app.post("/api/field-pilot/learning/{candidate_id}/disagree", include_in_schema=False)
    def operator_disagree(candidate_id: str, decision: OperatorDecision, request: Request):
        request.state.audit_operation = "FIELD_PILOT_LEARNING_DISAGREE"
        try:
            return service.learning.operator_decide(
                candidate_id, decision.kind, disagree=True,
                actor=service.learning_operator_id,
            )
        except (AttributeError, ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse({"message": "管理担当者へご確認ください"}, status_code=409)

    def require_admin(request: Request) -> bool:
        configured = service.learning_admin_token
        supplied = request.headers.get("x-field-pilot-admin-token", "")
        return bool(configured and supplied) and hmac.compare_digest(configured, supplied)

    @app.get("/api/field-pilot/admin", include_in_schema=False)
    def admin_view(request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        request.state.audit_operation = "FIELD_PILOT_LEARNING_ADMIN_VIEW"
        return service.learning.admin_view()

    @app.post("/api/field-pilot/admin/approve/{candidate_id}", include_in_schema=False)
    def admin_approve(candidate_id: str, decision: AdminDecision, request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        request.state.audit_operation = "FIELD_PILOT_LEARNING_ADMIN_APPROVE"
        try:
            return service.learning.admin_approve(
                candidate_id, decision.kind,
                decision.model_dump(exclude={"kind", "actor"}), decision.actor,
            )
        except (AttributeError, ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse({"message": "候補と正式条件を確認してください"}, status_code=409)

    @app.post("/api/field-pilot/admin/reject/{candidate_id}", include_in_schema=False)
    def admin_reject(candidate_id: str, decision: AdminDecision, request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        request.state.audit_operation = "FIELD_PILOT_LEARNING_ADMIN_REJECT"
        try:
            return service.learning.admin_reject(candidate_id, decision.actor)
        except (AttributeError, ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse({"message": "候補を確認してください"}, status_code=409)

    @app.post("/api/field-pilot/admin/deactivate/{version}", include_in_schema=False)
    def admin_deactivate(version: str, decision: AdminDecision, request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        request.state.audit_operation = "FIELD_PILOT_LEARNING_ADMIN_DEACTIVATE"
        try:
            service.learning.admin_deactivate(version, decision.actor)
            return {"status": "INACTIVE"}
        except (AttributeError, ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse({"message": "契約版を確認してください"}, status_code=409)
