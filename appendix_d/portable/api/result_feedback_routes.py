"""Operator result routes share the original, verified forecast resolver."""

import json

from fastapi import HTTPException, Request, Response

from portable.runtime.feedback_admin import authorized
from portable.runtime.installation import load_profile

from .result_feedback import FeedbackConflict, ResultFeedback, export_results


def register_result_feedback_routes(app, paths, resolve, read_limited):
    ledger = ResultFeedback(paths.state / "result-feedback.sqlite3")

    @app.get("/api/operator-results/{kind}/{reference}")
    def view(kind: str, reference: str):
        return ledger.view(f"{kind}:{reference}", resolve(kind, reference))

    @app.post("/api/operator-results/{kind}/{reference}/feedback", status_code=201)
    async def save(kind: str, reference: str, request: Request):
        predictions = resolve(kind, reference)
        try:
            payload = json.loads(await read_limited(request, 16 * 1024))
            if not isinstance(payload, dict):
                raise ValueError("入力内容を確認してください")
            exceptional = payload.get("exceptional") is True
            if exceptional and not authorized(paths, request.headers.get("x-feedback-admin", "")):
                raise HTTPException(403, "例外修正にはWindows管理者の一時認証が必要です")
            return ledger.save(
                f"{kind}:{reference}",
                predictions,
                payload,
                load_profile(paths.root),
                exceptional=exceptional,
            )
        except FeedbackConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/operator-results/{kind}/{reference}/download")
    async def download(kind: str, reference: str, request: Request):
        current = view(kind, reference)
        try:
            payload = json.loads(await read_limited(request, 1024 * 1024))
            if not isinstance(payload, dict):
                raise ValueError("保存対象を確認してください")
            data = export_results(current, payload.get("selected"))
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(
            data,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="forecast-results.csv"'},
        )
