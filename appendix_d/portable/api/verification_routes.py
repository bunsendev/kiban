"""Local accuracy read model and authenticated cutoff policy changes."""

import json
from datetime import date
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from portable.runtime.feedback_admin import authorized

from .forecast_verification import ForecastVerification
from .result_feedback import ResultFeedback


def register_verification_routes(app, paths, read_limited):
    ledger = ForecastVerification(paths.state / "forecast-verification.sqlite3")

    @app.get("/forecast-verification")
    def screen():
        return FileResponse(Path(__file__).parent / "static/field/accuracy.html")

    @app.get("/api/forecast-verification")
    def sources():
        return {
            "sources": ledger.sources(),
            "policy": ledger.policy(),
            "notice": "実績ファイルの正式取込時に確定。候補・隔離・欠測は未確定です。",
        }

    @app.get("/api/forecast-verification/compare")
    def compare(source: str, start: str = "", end: str = ""):
        try:
            for value in [start, end]:
                if value:
                    date.fromisoformat(value)
            if start and end and start > end:
                raise ValueError()
            feedback = ResultFeedback(paths.state / "result-feedback.sqlite3").history(source)
            adjusted = {(r["unique_id"], r["target_date"]): r.get("quantity") for r in feedback}
            return ledger.compare(source, start or None, end or None, adjusted)
        except ValueError as exc:
            raise HTTPException(422, "対象期間または保存履歴を確認してください") from exc

    @app.post("/api/forecast-verification/policy")
    async def policy(request: Request):
        if not authorized(paths, request.headers.get("x-feedback-admin", "")):
            raise HTTPException(403, "Windows管理者が発行する一時認証が必要です")
        try:
            value = json.loads(await read_limited(request, 4096))
            return ledger.set_policy(value.get("cutoff"), value.get("actor"), value.get("reason"))
        except (ValueError, AttributeError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
