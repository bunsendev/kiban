"""HTTP boundary for resumable daily Portable runs."""

import json
from contextlib import contextmanager

from fastapi import HTTPException, Request

from .daily_auto_run import DailyAutoRunError, PortableDailyAutoRun


def register_daily_auto_run_routes(
    app, paths, read_limited, production_workflow
) -> PortableDailyAutoRun:
    service = PortableDailyAutoRun(paths, production_workflow)

    @contextmanager
    def exclusive_operation():
        with app.state.lock:
            if app.state.closing:
                raise HTTPException(503, "終了処理中です")
            if app.state.active:
                raise HTTPException(409, "別の処理を実行中です")
            app.state.active += 1
        try:
            yield
        finally:
            with app.state.lock:
                app.state.active -= 1

    @app.get("/api/daily-runs")
    def daily_runs():
        return service.list()

    @app.get("/api/daily-runs/{analysis_id}")
    def daily_run(analysis_id: str):
        try:
            return service.view(analysis_id)
        except DailyAutoRunError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/daily-runs/{analysis_id}/advance", status_code=201)
    async def advance_daily_run(analysis_id: str, request: Request):
        try:
            payload = json.loads(await read_limited(request, 16 * 1024) or b"{}")
            if not isinstance(payload, dict):
                raise DailyAutoRunError("確認内容を確認してください")
            with exclusive_operation():
                return service.advance(analysis_id, payload)
        except (DailyAutoRunError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/daily-runs/{analysis_id}/daily-summary", status_code=201)
    async def prepare_daily_decision(analysis_id: str, request: Request):
        try:
            payload = json.loads(await read_limited(request, 16 * 1024) or b"{}")
            if not isinstance(payload, dict):
                raise DailyAutoRunError("賞味期限の確認条件を確認してください")
            with exclusive_operation():
                return service.prepare_decision(analysis_id, payload)
        except (DailyAutoRunError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/daily-runs/{analysis_id}/decision-inputs", status_code=201)
    async def submit_daily_decision_inputs(analysis_id: str, request: Request):
        try:
            payload = json.loads(
                await read_limited(request, 8 * 1024 * 1024) or b"{}"
            )
            if not isinstance(payload, dict):
                raise DailyAutoRunError("正式Decision入力を確認してください")
            with exclusive_operation():
                return service.submit_decision_inputs(analysis_id, payload)
        except (DailyAutoRunError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/daily-runs/{analysis_id}/decision-inputs/requirements")
    def guided_daily_decision_requirements(analysis_id: str):
        try:
            return service.decision_requirements(analysis_id)
        except DailyAutoRunError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post(
        "/api/daily-runs/{analysis_id}/decision-inputs/guided", status_code=201
    )
    async def submit_guided_daily_decision_inputs(analysis_id: str, request: Request):
        try:
            payload = json.loads(await read_limited(request, 2 * 1024 * 1024) or b"{}")
            if not isinstance(payload, dict):
                raise DailyAutoRunError("画面入力の工場・配送条件を確認してください")
            with exclusive_operation():
                return service.submit_guided_decision_inputs(analysis_id, payload)
        except (DailyAutoRunError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    return service
