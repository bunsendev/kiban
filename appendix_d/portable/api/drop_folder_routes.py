"""HTTP read and manual rescan boundary for the Portable drop folder."""

import json

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from forecast_provider.field_pilot.ai_intake import AiSuggestionUnavailable

from .business_archive import ArchiveError
from .drop_folder import DropFolderBusyError, DropFolderError


def register_drop_folder_routes(app, service) -> None:
    async def payload(request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 32768:
                raise HTTPException(413, "入力が大きすぎます")
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or not isinstance(value.get("sha256"), str):
                raise ValueError()
            return value
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, "画面を更新して入力し直してください") from exc

    @app.get("/api/drop-folder/review")
    def review_files():
        with service._lock:
            return service.review.candidates()

    @app.post("/api/drop-folder/approve")
    async def approve_file(request: Request):
        value = await payload(request)

        def save():
            with service._lock:
                result = service.review.approve(value)
                service._csv_attempt = None
                return result
        try:
            return await run_in_threadpool(save)
        except (ArchiveError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/drop-folder/ai-suggest")
    async def ai_suggest(request: Request):
        value = await payload(request)
        try:
            return await run_in_threadpool(service.review.suggest, value)
        except AiSuggestionUnavailable as exc:
            raise HTTPException(503, "AI提案を取得できません。手動で列を選択できます。") from exc
        except (ArchiveError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/drop-folder")
    def drop_folder():
        return service.view()

    @app.post("/api/drop-folder/scan")
    def scan_drop_folder():
        try:
            return service.scan(force=True)
        except DropFolderBusyError as exc:
            raise HTTPException(409, str(exc)) from exc
        except DropFolderError as exc:
            raise HTTPException(422, str(exc)) from exc
