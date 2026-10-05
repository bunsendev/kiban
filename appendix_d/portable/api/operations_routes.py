"""Field-visible feedback delivery and update controls, with opt-in configuration."""

import json
import os
import sys
import threading
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from portable import APP_VERSION
from portable.runtime.feedback_admin import authorized, instance_id
from portable.runtime.feedback_delivery import FeedbackDelivery, receiver_identity
from portable.runtime.feedback_profiles import FeedbackProfiles
from portable.runtime.release_update import ReleaseUpdate


def register_operations(app, paths, read_limited, control_token):
    delivery = FeedbackDelivery(paths)
    profiles = FeedbackProfiles(paths)
    root = (
        Path(sys.executable).resolve().parent.parent
        if getattr(sys, "frozen", False)
        else paths.root.parent
    )
    updates = ReleaseUpdate(root)
    app.state.delivery = delivery
    app.state.updates = updates
    update_lock = threading.Lock()
    app.state.update_requested = None
    app.state.operations_writes = 0

    def require_admin(request):
        if not authorized(paths, request.headers.get("x-feedback-admin", "")):
            raise HTTPException(403, "管理者用の設定起動から開き直してください（有効期限15分）")

    @app.get("/api/operations/instance")
    def instance():
        return {"instance_id": instance_id(paths)}

    @app.get("/feedback-admin")
    def admin_page():
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).parent / "static/field/feedback-admin.html")

    @app.get("/api/operations/admin-config")
    def admin_config(request: Request):
        require_admin(request)
        return delivery.status()

    @app.get("/api/operations/device-profiles")
    def device_profiles(request: Request):
        require_admin(request)
        return profiles.summaries()

    @app.middleware("http")
    async def operation_guard(request, next_handler):
        write = request.method not in {"GET", "HEAD", "OPTIONS"}
        with app.state.lock:
            if (
                app.state.update_requested
                and write
                and not request.url.path.startswith("/api/control/")
            ):
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    {"detail": "更新準備中です。再起動をお待ちください"}, status_code=503
                )
            if write:
                app.state.operations_writes += 1
        try:
            return await next_handler(request)
        finally:
            if write:
                with app.state.lock:
                    app.state.operations_writes -= 1

    def startup():
        if os.environ.get("PORTABLE_SMOKE") == "1":
            return

        def run():
            try:
                delivery.send()
            except Exception:
                pass  # Outbox retains unsent work; status UI exposes configuration/errors.
            with update_lock:
                updates.check()

        threading.Thread(target=run, daemon=True).start()

    app.router.add_event_handler("startup", startup)

    @app.get("/api/operations/status")
    def status():
        feedback = delivery.status()
        feedback["config"] = {"enabled": feedback["config"]["enabled"]}
        return {
            "feedback": feedback,
            "update": updates.status(),
            "can_apply": bool(control_token and getattr(sys, "frozen", False)),
            "version": APP_VERSION,
        }

    @app.post("/api/operations/{action}")
    async def action(action: str, request: Request):
        try:
            value = json.loads(await read_limited(request, 65536))
            if not isinstance(value, dict):
                raise ValueError("入力内容を確認してください")
            if action in {"profile-import", "profile-apply"}:
                require_admin(request)
                if action == "profile-import":
                    return await run_in_threadpool(profiles.import_profiles, value)
                return await run_in_threadpool(profiles.apply, delivery, value)
            if action == "configure":
                require_admin(request)
                if value.get("enabled") is not False:
                    if (not value.get("key_id") or value.get("key_fingerprint")
                            != receiver_identity(value.get("public_key"))):
                        raise ValueError("KEY_CONFIRMATION_REQUIRED")
                return await run_in_threadpool(delivery.configure, value)
            if action == "key-preview":
                require_admin(request)
                return {"key_fingerprint": receiver_identity(value.get("public_key"))}
            if action == "send":
                return await run_in_threadpool(delivery.send, manual=True)
            if action == "connection-test":
                require_admin(request)
                return await run_in_threadpool(delivery.connection_test)
            if action == "finish-day":
                return await run_in_threadpool(delivery.finish_day)
            if action == "update-check":
                if not update_lock.acquire(blocking=False):
                    raise ValueError("更新処理中です")
                try:
                    return await run_in_threadpool(updates.check)
                finally:
                    update_lock.release()
            if action == "update-apply":
                if not control_token or not getattr(sys, "frozen", False):
                    raise ValueError("「ブンセン予測を起動.cmd」から起動して更新してください")
                if value.get("confirm") is not True:
                    raise ValueError("バックアップと再起動への確認が必要です")
                if not update_lock.acquire(blocking=False):
                    raise ValueError("更新処理中です")
                try:
                    staged = await run_in_threadpool(updates.stage)
                    with app.state.lock:
                        if app.state.active or app.state.operations_writes > 1:
                            raise ValueError("業務処理中です。完了後に更新を確認し直してください")
                        app.state.update_requested = staged["stage"]
                        app.state.closing = True
                    return {"status": "RESTART_REQUESTED"}
                finally:
                    update_lock.release()
            raise HTTPException(404)
        except (ValueError, OSError, InvalidSignature, KeyError, TypeError):
            # Never propagate token, raw network response, or a private file path.
            raise HTTPException(
                422, "操作できません。設定・処理状況・公開鍵を確認してください"
            ) from None

    @app.post("/api/control/finish-day")
    async def finish(request: Request):
        if not control_token or request.headers.get("x-portable-control") != control_token:
            raise HTTPException(403)
        try:
            return await run_in_threadpool(delivery.finish_day)
        except Exception:
            return {"status": "SAVED_FOR_RETRY"}

    return delivery, updates
