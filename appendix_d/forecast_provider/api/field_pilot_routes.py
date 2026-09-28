"""Field Pilot専用のloopback Shadow境界と限定された学習メタデータ操作。"""

import hmac
import json
import re
import sqlite3
from datetime import date, datetime
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..field_pilot.ai_intake import AiSuggestionUnavailable
from ..field_pilot.operator_feedback import (
    OperatorAction,
    OperatorFeedback,
    record_action,
    record_feedback,
)
from ..inventory_foundation.read_service import InventoryReadError

LEARNING_ACTION = re.compile(r"^/api/field-pilot/learning/[0-9a-f]{64}/(confirm|disagree)$")
AI_ACTION = re.compile(r"^/api/field-pilot/learning/[0-9a-f]{64}/suggest$")
ADMIN_ACTION = re.compile(
    r"^/api/field-pilot/admin/(approve|reject)/[0-9a-f]{64}$"
    r"|^/api/field-pilot/admin/deactivate/learned-[0-9a-f]{24}$"
)
FORMAL_APPROVAL = re.compile(r"^/api/field-pilot/admin/formal-jobs/[a-zA-Z0-9-]+/approve$")


class OperatorDecision(BaseModel):
    kind: str


class AiSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str | None = None


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


class SettingChange(BaseModel):
    change_type: str
    target: str
    value: dict
    effective_from: date
    actor: str
    reason_code: str
    comment: str = ""
    expected_version: str | None = None


class SettingRollback(BaseModel):
    version: str
    actor: str
    expected_version: str
    comment: str = ""


class FeedbackPolicyChange(BaseModel):
    policy: dict
    expected_version: str | None = None
    actor: str
    reason: str


class SupportConsent(BaseModel):
    target: str
    purpose: str
    destination: str
    actor: str
    expires_at: datetime


class FormalInventoryApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str
    reason: str
    expected_revision: int = 0


class ConfirmedJanPublication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str
    reason: str


class ShipmentTrialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_code: str


class ShipmentTrialFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_code: str
    source_fingerprint: str
    issue: str


def install_field_pilot_routes(app: FastAPI, service) -> None:
    operator_paths = {
        "/api/field-pilot/operator-feedback",
        "/api/field-pilot/operator-action",
    }
    allowed_paths = {
        "/health", "/ready", "/ui/pilot", "/ui/pilot/", "/api/field-pilot/view",
        "/api/field-pilot/inbox",
        "/api/field-pilot/learning", "/api/field-pilot/admin",
        "/api/field-pilot/admin/unresolved-products",
        "/api/field-pilot/admin/update",
        "/ui/pilot/admin", "/ui/pilot/admin/",
        "/ui/pilot/settings", "/ui/pilot/settings/",
        "/api/field-pilot/settings",
        "/api/field-pilot/feedback",
        "/ui/pilot/feedback", "/ui/pilot/feedback/",
        "/ui/assets/pilot.css", "/ui/assets/pilot.js",
        "/ui/assets/pilot_admin.js",
        "/ui/assets/pilot_settings.js",
        "/ui/assets/pilot_feedback.js",
    }

    @app.middleware("http")
    async def field_pilot_boundary(request: Request, call_next):
        path = request.url.path
        if request.url.hostname not in {"127.0.0.1", "localhost"}:
            return JSONResponse({"message": "現場PC内からのみ利用できます"}, status_code=403)
        if (path in {"/api/field-pilot/admin",
                     "/api/field-pilot/admin/update",
                     "/api/field-pilot/admin/update/check",
                     "/api/field-pilot/admin/product-mapping/publish",
                     "/api/field-pilot/admin/shipment-trial",
                     "/api/field-pilot/admin/shipment-trial/feedback"}
                or ADMIN_ACTION.fullmatch(path)
                or FORMAL_APPROVAL.fullmatch(path)
                or path.startswith("/api/field-pilot/settings")
                or path.startswith("/api/field-pilot/feedback")):
            configured = service.learning_admin_token
            supplied = request.headers.get("x-field-pilot-admin-token", "")
            if not (configured and supplied) or not hmac.compare_digest(configured, supplied):
                return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        if request.method == "POST":
            if not (LEARNING_ACTION.fullmatch(path) or AI_ACTION.fullmatch(path)
                    or ADMIN_ACTION.fullmatch(path)
                    or FORMAL_APPROVAL.fullmatch(path)
                    or path in {"/api/field-pilot/admin/product-mapping/publish",
                                "/api/field-pilot/admin/update/check",
                                "/api/field-pilot/admin/shipment-trial",
                                "/api/field-pilot/admin/shipment-trial/feedback",
                                "/api/field-pilot/settings/change",
                                "/api/field-pilot/settings/rollback",
                                "/api/field-pilot/feedback/change",
                                "/api/field-pilot/feedback/support-consent"}
                    or path in operator_paths):
                return JSONResponse({"message": "試験運用は読み取り専用です"}, status_code=405)
            if not request.headers.get("content-type", "").startswith("application/json"):
                return JSONResponse({"message": "要求形式を確認してください"}, status_code=415)
            origin = request.headers.get("origin")
            if path in operator_paths:
                length = request.headers.get("content-length", "")
                if (request.headers.get("x-field-pilot-operator") != "1"
                        or not length.isdigit() or int(length) > 1024):
                    return JSONResponse({"message": "要求形式を確認してください"}, status_code=403)
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

    @app.post("/api/field-pilot/learning/{candidate_id}/suggest", include_in_schema=False)
    def learning_ai_suggest(candidate_id: str, decision: AiSuggestionRequest,
                            request: Request):
        request.state.audit_operation = "FIELD_PILOT_AI_SUGGESTION"
        if not re.fullmatch(r"[0-9a-f]{64}", candidate_id):
            return JSONResponse({"message": "候補を確認してください"}, status_code=404)
        try:
            return service.learning.ai_suggest(candidate_id, api_key=decision.api_key)
        except AiSuggestionUnavailable:
            return JSONResponse(
                {"message": "AI候補を取得できません。通常の確認を続けてください。"},
                status_code=503,
            )
        except (AttributeError, ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse({"message": "候補を再確認してください"}, status_code=409)

    @app.get("/api/field-pilot/admin/unresolved-products", include_in_schema=False)
    def unresolved_products_view(request: Request):
        request.state.audit_operation = "FIELD_PILOT_UNRESOLVED_PRODUCTS_VIEW"
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        try:
            return service.unresolved_products_view()
        except (AttributeError, OSError, ValueError, sqlite3.DatabaseError):
            return JSONResponse({"message": "未確定商品を確認できませんでした"}, status_code=503)

    @app.post("/api/field-pilot/admin/formal-jobs/{job_id}/approve",
              include_in_schema=False)
    def approve_formal_inventory(job_id: str, value: FormalInventoryApproval,
                                 request: Request):
        request.state.audit_operation = "FIELD_PILOT_FORMAL_INVENTORY_APPROVAL"
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        try:
            return service.approve_formal_inventory(job_id, **value.model_dump())
        except (AttributeError, OSError, ValueError, sqlite3.DatabaseError,
                InventoryReadError):
            return JSONResponse(
                {"message": "検証結果・隔離行・版を確認してください"}, status_code=409
            )

    @app.post("/api/field-pilot/admin/product-mapping/publish",
              include_in_schema=False)
    def publish_confirmed_jan(value: ConfirmedJanPublication, request: Request):
        request.state.audit_operation = "FIELD_PILOT_JAN_MAPPING_PUBLICATION"
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        try:
            return service.publish_confirmed_jan(**value.model_dump())
        except (AttributeError, OSError, ValueError, sqlite3.DatabaseError):
            return JSONResponse(
                {"message": "原本・JAN確認履歴と出荷履歴の矛盾を確認してください"},
                status_code=409,
            )

    @app.post("/api/field-pilot/admin/shipment-trial", include_in_schema=False)
    def shipment_trial(value: ShipmentTrialRequest, request: Request):
        request.state.audit_operation = "FIELD_PILOT_SHIPMENT_TRIAL"
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        try:
            return service.shipment_trial(value.product_code)
        except (AttributeError, OSError, ValueError, sqlite3.DatabaseError):
            return JSONResponse({"message": "JAN・原本・試算条件を確認してください"},
                                status_code=409)

    @app.post("/api/field-pilot/admin/shipment-trial/feedback",
              include_in_schema=False)
    def shipment_trial_feedback(value: ShipmentTrialFeedback, request: Request):
        request.state.audit_operation = "FIELD_PILOT_SHIPMENT_TRIAL_FEEDBACK"
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        try:
            return service.shipment_trial_feedback(**value.model_dump())
        except (AttributeError, OSError, ValueError, sqlite3.DatabaseError):
            return JSONResponse({"message": "現在の試算結果を再確認してください"},
                                status_code=409)

    @app.post("/api/field-pilot/operator-feedback", include_in_schema=False)
    def operator_feedback(value: OperatorFeedback, request: Request):
        request.state.audit_operation = "FIELD_PILOT_OPERATOR_FEEDBACK"
        try:
            record_feedback(service.improvement_events, value)
            return {"status": "RECORDED"}
        except (AttributeError, OSError, ValueError, sqlite3.DatabaseError):
            return JSONResponse({"message": "記録できませんでした"}, status_code=503)

    @app.post("/api/field-pilot/operator-action", include_in_schema=False)
    def operator_action(value: OperatorAction, request: Request):
        request.state.audit_operation = "FIELD_PILOT_OPERATOR_ACTION"
        try:
            record_action(service.improvement_events, value)
            return {"status": "RECORDED"}
        except (AttributeError, OSError, ValueError, sqlite3.DatabaseError):
            return JSONResponse({"message": "記録できませんでした"}, status_code=503)

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

    @app.get("/api/field-pilot/feedback", include_in_schema=False)
    def feedback_view(request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        current = service.feedback_store.current()
        config = None
        config_path = service.config_path.parent / "feedback-client.json"
        try:
            if config_path.is_file() and not config_path.is_symlink() and (
                config_path.stat().st_size <= 4096
            ):
                source = json.loads(config_path.read_text(encoding="utf-8-sig"))
                config = {"endpoint": source.get("endpoint"),
                          "client_id": source.get("client_id")}
        except (OSError, ValueError, TypeError):
            config = None
        try:
            app_version = version("bunsen-forecast-provider")
        except PackageNotFoundError:
            app_version = "unpackaged"
        return {**current, "application_version": app_version, "connection": config,
                "sync": service.feedback_store.status(), "preview": {
            "sends": (["診断・処理状態"] if current["policy"]["flags"]["diagnostics"] else [])
            + (["集計した処理時間・改善指標"]
               if current["policy"]["flags"]["forecast_metrics"] else [])
            + (["疑似IDを付けた詳細"] if current["policy"]["level"] == 3 else []),
            "never_in_regular_sync": ["原本CSV/PDF", "商品名", "取引先名", "資格情報"],
            "status": "送信OFF" if current["policy"]["level"] == 0 else "中央側の同意確認が必要",
        }}

    @app.post("/api/field-pilot/feedback/change", include_in_schema=False)
    def feedback_change(decision: FeedbackPolicyChange, request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        try:
            return service.feedback_store.change(
                decision.policy, expected_version=decision.expected_version,
                actor=decision.actor, reason=decision.reason,
            )
        except (ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse({"message": "共有範囲・版を確認してください"}, status_code=409)

    @app.post("/api/field-pilot/feedback/support-consent", include_in_schema=False)
    def feedback_support_consent(decision: SupportConsent, request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        try:
            consent_id = service.feedback_store.consent(**decision.model_dump())
            return {"consent_id": consent_id, "status": "ONE_TIME"}
        except (ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse({"message": "対象と期限を確認してください"}, status_code=409)

    @app.get("/api/field-pilot/settings", include_in_schema=False)
    def settings_view(request: Request, change_type: str = "JAN_MAPPING", target: str = ""):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        request.state.audit_operation = "FIELD_PILOT_SETTINGS_VIEW"
        try:
            store = service.local_settings.store
            targets = store.targets(change_type)
            if target:
                history = store.history(change_type, target)
                return {"targets": targets, "current": store.current(change_type, target),
                        "latest_version": history[0]["version"] if history else None,
                        "history": history}
            return {"targets": targets, "current": None, "latest_version": None,
                    "history": []}
        except (AttributeError, ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse({"message": "設定を確認できません"}, status_code=409)

    @app.post("/api/field-pilot/settings/change", include_in_schema=False)
    def settings_change(decision: SettingChange, request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        request.state.audit_operation = "FIELD_PILOT_SETTINGS_CHANGE"
        try:
            return service.local_settings.change(**decision.model_dump())
        except (AttributeError, ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse(
                {"message": "入力内容・版・Backupを確認してください"}, status_code=409,
            )

    @app.post("/api/field-pilot/settings/rollback", include_in_schema=False)
    def settings_rollback(decision: SettingRollback, request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        request.state.audit_operation = "FIELD_PILOT_SETTINGS_ROLLBACK"
        try:
            return service.local_settings.restore_previous(**decision.model_dump())
        except (AttributeError, ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse(
                {"message": "復帰先・現在版・Backupを確認してください"}, status_code=409,
            )

    @app.get("/api/field-pilot/admin", include_in_schema=False)
    def admin_view(request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        request.state.audit_operation = "FIELD_PILOT_LEARNING_ADMIN_VIEW"
        return {**service.learning.admin_view(),
                "formal_jobs": service.inbox_view().get("formal_jobs", [])}

    @app.get("/api/field-pilot/admin/update", include_in_schema=False)
    def admin_update_status(request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        request.state.audit_operation = "FIELD_PILOT_UPDATE_STATUS"
        try:
            return service.update_service.status()
        except (ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse({"message": "更新設定を確認してください"}, status_code=409)

    @app.post("/api/field-pilot/admin/update/check", include_in_schema=False)
    def admin_update_check(request: Request):
        if not require_admin(request):
            return JSONResponse({"message": "管理者確認が必要です"}, status_code=403)
        request.state.audit_operation = "FIELD_PILOT_UPDATE_CHECK"
        try:
            return service.update_service.check(trigger="MANUAL", force=True)
        except (ValueError, OSError, sqlite3.DatabaseError):
            return JSONResponse({"message": "更新確認を実行できません"}, status_code=409)

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
