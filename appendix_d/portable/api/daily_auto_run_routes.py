"""HTTP boundary for resumable daily Portable runs."""

import json
import re
from contextlib import contextmanager

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from portable.runtime.performance import measure

from .daily_auto_run import DailyAutoRunError, PortableDailyAutoRun
from .forecast_batches import validate_batch_size


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
            validate_batch_size(payload.get("batch_size", 100))
            if not re.fullmatch(r"[0-9a-f]{64}", analysis_id):
                raise DailyAutoRunError("分析IDを確認してください")

            def execute():
                with (
                    exclusive_operation(),
                    measure(
                        paths.state / "Performance" / f"{analysis_id}.json",
                        stage="inventory_and_reference",
                        details={"batch_size": payload.get("batch_size", 100)},
                    ) as metrics,
                ):
                    result = service.advance(analysis_id, payload)
                    metrics.update(
                        series_count=result.get("eligible_series_count"),
                        production_run_id=result.get("production_run_id"),
                    )
                    return result

            return await run_in_threadpool(execute)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/performance/{analysis_id}")
    def performance(analysis_id: str):
        if not re.fullmatch(r"[0-9a-f]{64}", analysis_id):
            raise HTTPException(404, "分析IDを確認してください")
        path = paths.state / "Performance" / f"{analysis_id}.json"
        if not path.is_file():
            return {"stages": []}
        try:
            first = json.loads(path.read_text(encoding="utf-8"))
            stages = [first]
            run_id = first.get("production_run_id", "") or ""
            if re.fullmatch(r"[0-9a-f-]{36}", run_id):
                production = path.with_name(f"production-{run_id}.json")
                if production.is_file():
                    stages.append(json.loads(production.read_text(encoding="utf-8")))
            return {"stages": stages}
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "計測結果を再取得してください") from exc

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
            payload = json.loads(await read_limited(request, 8 * 1024 * 1024) or b"{}")
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

    @app.post("/api/daily-runs/{analysis_id}/decision-inputs/guided", status_code=201)
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
