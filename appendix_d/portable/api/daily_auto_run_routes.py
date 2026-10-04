"""HTTP boundary for resumable daily Portable runs."""

import json

from fastapi import HTTPException, Request

from .daily_auto_run import DailyAutoRunError, PortableDailyAutoRun


def register_daily_auto_run_routes(app, paths, read_limited) -> PortableDailyAutoRun:
    service = PortableDailyAutoRun(paths)

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
            with app.state.lock:
                if app.state.closing:
                    raise HTTPException(503, "終了処理中です")
                if app.state.active:
                    raise HTTPException(409, "別の処理を実行中です")
                app.state.active += 1
            try:
                return service.advance(analysis_id, payload)
            finally:
                with app.state.lock:
                    app.state.active -= 1
        except (DailyAutoRunError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    return service
