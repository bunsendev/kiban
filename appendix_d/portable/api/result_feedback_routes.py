"""Operator result routes share the original, verified forecast resolver."""

import json

from fastapi import HTTPException, Query, Request, Response

from portable.runtime.feedback_admin import authorized
from portable.runtime.installation import load_profile

from .result_feedback import FeedbackConflict, ResultFeedback, export_results
from .saved_forecasts import SavedForecasts


def register_result_feedback_routes(app, paths, resolve, read_limited, forecast, production):
    ledger = ResultFeedback(paths.state / "result-feedback.sqlite3")

    catalog = SavedForecasts(forecast, production)
    app.state.saved_forecasts = catalog

    @app.get("/api/saved-forecasts")
    def saved_forecasts(warehouse: str = "", offset: int = Query(0, ge=0),
                        limit: int = Query(50, ge=1, le=100)):
        return catalog.list(warehouse, offset, limit)

    def predictions(kind, reference, warehouse):
        try:
            return catalog.filter_rows(kind, reference, resolve(kind, reference), warehouse)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/operator-results/{kind}/{reference}")
    def view(kind: str, reference: str, warehouse: str = ""):
        value = ledger.view(f"{kind}:{reference}", predictions(kind, reference, warehouse))
        if kind == "production" and catalog is not None:
            manifest = catalog.manifest(reference)
            value.update({k: manifest[k]
                          for k in ("provisional", "forecast_mode", "quality_check_id")
                          if k in manifest})
        ids = {r["unique_id"] for r in value["rows"]}
        value["history"] = [r for r in value["history"] if r["unique_id"] in ids]
        return value

    @app.post("/api/operator-results/{kind}/{reference}/feedback", status_code=201)
    async def save(kind: str, reference: str, request: Request, warehouse: str = ""):
        rows = predictions(kind, reference, warehouse)
        try:
            payload = json.loads(await read_limited(request, 16 * 1024))
            if not isinstance(payload, dict):
                raise ValueError("入力内容を確認してください")
            exceptional = payload.get("exceptional") is True
            if exceptional and not authorized(paths, request.headers.get("x-feedback-admin", "")):
                raise HTTPException(403, "例外修正にはWindows管理者の一時認証が必要です")
            return ledger.save(
                f"{kind}:{reference}",
                rows,
                payload,
                load_profile(paths.root),
                exceptional=exceptional,
            )
        except FeedbackConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/operator-results/{kind}/{reference}/download")
    async def download(kind: str, reference: str, request: Request, warehouse: str = ""):
        current = view(kind, reference, warehouse)
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
