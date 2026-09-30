"""HTTP routes for the Portable to Unified Inbox formal inventory pipeline."""

import json
import re

from fastapi import HTTPException, Request

from .formal_pipeline import PortableFormalPipeline
from .formal_pipeline_contracts import FormalPipelineError


def register_formal_pipeline_routes(app, paths, read_limited) -> None:
    pipeline = PortableFormalPipeline(paths)

    @app.get("/api/formal-inventory/{handoff_id}/pipeline")
    def formal_pipeline_view(handoff_id: str):
        try:
            return pipeline.view(handoff_id)
        except FormalPipelineError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/formal-inventory/{handoff_id}/pipeline", status_code=201)
    async def register_formal_pipeline(handoff_id: str, request: Request):
        try:
            payload = json.loads(await read_limited(request, 64 * 1024) or b"{}")
            if not isinstance(payload, dict):
                raise FormalPipelineError("試験対象の確認内容を確認してください")
            with app.state.lock:
                if app.state.closing:
                    raise HTTPException(503, "終了処理中です")
                if app.state.active:
                    raise HTTPException(409, "別の処理を実行中です")
                app.state.active += 1
            try:
                return pipeline.register(handoff_id, payload)
            finally:
                with app.state.lock:
                    app.state.active -= 1
        except (FormalPipelineError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post(
        "/api/formal-inventory/pipeline/{registration_id}/jobs/{job_id}/approve",
        status_code=201,
    )
    async def approve_formal_pipeline_job(registration_id: str, job_id: str, request: Request):
        if not re.fullmatch(r"[0-9a-f]{64}", registration_id):
            raise HTTPException(404, "正式取込登録が見つかりません")
        try:
            payload = json.loads(await read_limited(request, 16 * 1024) or b"{}")
            if not isinstance(payload, dict):
                raise FormalPipelineError("承認内容を確認してください")
            return pipeline.approve(registration_id, job_id, payload)
        except (FormalPipelineError, json.JSONDecodeError) as exc:
            raise HTTPException(409, str(exc)) from exc
