"""Back up while idle; queue restoration for the next process start."""

import json
import re
import sqlite3
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from portable.runtime.learning_backup import LIMIT, LearningBackup


def register_learning_backup(app, paths, read_limited):
    recovery = LearningBackup(paths.root)
    app.state.recovery_pending = recovery.status()["pending"]
    app.state.recovery_busy = False

    @contextmanager
    def idle():
        with app.state.lock:
            if app.state.active or app.state.closing or app.state.operations_writes > 1:
                raise HTTPException(409, "分析・取込・設定処理の完了後に実行してください")
            app.state.active += 1
            app.state.recovery_busy = True
        try:
            yield
        finally:
            with app.state.lock:
                app.state.active -= 1
                app.state.recovery_busy = False

    @app.middleware("http")
    async def guard(request, next_handler):
        if (
            (app.state.recovery_pending or app.state.recovery_busy)
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.url.path != "/api/learning-backup/cancel"
            and not request.url.path.startswith("/api/control/")
        ):
            return JSONResponse(
                {"detail": "バックアップ・復元の処理中です。完了または再起動をお待ちください。"},
                409,
            )
        return await next_handler(request)

    @app.get("/learning-backup")
    def screen():
        return FileResponse(Path(__file__).parent / "static/field/learning-backup.html")

    @app.get("/api/learning-backup/status")
    def status():
        return recovery.status()

    @app.post("/api/learning-backup/create")
    async def create():
        try:
            with idle():
                path = await run_in_threadpool(recovery.create)
            return FileResponse(path, filename=path.name, media_type="application/zip")
        except (ValueError, OSError, sqlite3.DatabaseError, zipfile.BadZipFile) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/learning-backup/preview")
    async def preview(request: Request):
        raw = await read_limited(request, LIMIT)
        name = uuid.uuid4().hex
        path = recovery.work / ("upload-" + name + ".zip")
        path.write_bytes(raw)
        try:
            with idle():
                info = await run_in_threadpool(recovery.inspect, path)
            return {k: v for k, v in info.items() if k != "entries"} | {"id": name}
        except (ValueError, OSError, sqlite3.DatabaseError, zipfile.BadZipFile) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/learning-backup/restore")
    async def restore(request: Request):
        try:
            value = json.loads(await read_limited(request, 4096))
            ident = str(value.get("id", ""))
            if not re.fullmatch("[0-9a-f]{32}", ident):
                raise ValueError("検証したバックアップを選んでください")
            with idle():
                result = await run_in_threadpool(
                    recovery.stage,
                    recovery.work / ("upload-" + ident + ".zip"),
                    confirm=value.get("confirm") is True,
                    allow_legacy=value.get("allow_legacy") is True,
                )
                app.state.recovery_pending = True
            return result
        except (ValueError, OSError, sqlite3.DatabaseError, zipfile.BadZipFile) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/learning-backup/cancel")
    def cancel():
        if app.state.recovery_busy:
            raise HTTPException(409, "処理が完了してから取消してください")
        recovery.cancel()
        app.state.recovery_pending = False
        return {"status": "CANCELLED"}
