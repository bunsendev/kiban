"""Local field UI endpoints; business services remain the source of truth."""

import csv
import hashlib
import io
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from forecast_provider.operation_events.domain import make_operation_event
from forecast_provider.operation_events.store import SqliteOperationEventStore

from .business_archive import MAX_ZIP_BYTES, atomic_json
from .field_read_model import build_view, export, page, safe_csv, with_reviews
from .field_store import FieldStore
from .field_workflow import FieldWorkflow
from .result_feedback import FeedbackConflict

STATIC = Path(__file__).parent / "static" / "field"


def register_field_routes(app, paths, intake, daily, resolve, read_limited):
    store = FieldStore(paths.state / "field-ui.sqlite3")
    workflow = FieldWorkflow(app, store, intake, daily)
    events = SqliteOperationEventStore(paths.state / "field-operation-events.sqlite3")
    snapshots = paths.state / "FieldResults"
    snapshots.mkdir(exist_ok=True)
    exports = paths.state / "FieldExports"
    exports.mkdir(exist_ok=True)
    app.state.field_store = store

    async def payload(request, limit=16384):
        try:
            value = json.loads(await read_limited(request, limit))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, "入力内容を確認してください") from exc

    def snapshot(result_id):
        if not re.fullmatch(r"[0-9a-f]{64}", result_id):
            raise HTTPException(404, "結果が見つかりません")
        try:
            value = json.loads((snapshots / f"{result_id}.json").read_text("utf-8"))
            digest = value.pop("result_id")
            actual = hashlib.sha256(
                json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            if actual != digest or digest != result_id:
                raise ValueError()
            return value | {"result_id": digest}
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(409, "保存結果の整合性を確認できません") from exc

    @app.get("/field")
    @app.get("/field/")
    def index():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/field/manual")
    def manual():
        return FileResponse(STATIC / "manual.html", media_type="text/html")

    @app.get("/field/manual.css")
    def manual_style():
        return FileResponse(STATIC / "manual.css", media_type="text/css")

    @app.get("/field/assets/{name}")
    def asset(name: str):
        if name not in {p.name for p in STATIC.iterdir() if p.suffix in {".js", ".css"}}:
            raise HTTPException(404)
        return FileResponse(
            STATIC / name, media_type="text/css" if name.endswith(".css") else "text/javascript"
        )

    @app.get("/api/field/jobs")
    def jobs():
        return store.jobs()

    @app.get("/api/field/versions")
    def versions():
        values = []
        for path in sorted(snapshots.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            value = snapshot(path.stem)
            values.append(
                {
                    "result_id": path.stem,
                    "analysis_id": value["analysis_id"],
                    "count": len(value["rows"]),
                    "period": value["rows"][0]["period"] if value["rows"] else [],
                    "risk_evaluated": bool(value.get("summary_key")),
                }
            )
        return values

    @app.post("/api/field/upload", status_code=202)
    async def upload(request: Request):
        data = await read_limited(request, MAX_ZIP_BYTES)
        name = request.headers.get("x-file-name", "upload.zip")
        return workflow.start("UPLOAD", lambda: intake.ingest(data), filename=name)

    @app.post("/api/field/{analysis_id}/advance", status_code=202)
    async def advance(analysis_id: str, request: Request):
        value = await payload(request)
        if not re.fullmatch(r"[0-9a-f]{64}", analysis_id):
            raise HTTPException(422, "分析を確認してください")
        return workflow.start("ADVANCE", lambda: daily.advance(analysis_id, value), analysis_id)

    @app.get("/api/field/{analysis_id}/results")
    def results(analysis_id: str):
        try:
            value = build_view(daily, analysis_id, resolve)
            target = snapshots / f"{value['result_id']}.json"
            if not target.exists():
                atomic_json(target, value)
            return {"result_id": value["result_id"]}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/field/results/{result_id}")
    def result_page(
        result_id: str,
        q: str = "",
        warehouse: str = "",
        attention: bool = False,
        offset: int = Query(0, ge=0),
        limit: int = Query(30, ge=1, le=100),
    ):
        return page(
            with_reviews(snapshot(result_id), store), q, warehouse, attention, offset, limit
        )

    @app.get("/api/field/results/{result_id}/history")
    def history(result_id: str):
        snapshot(result_id)
        return store.history(result_id)

    @app.get("/api/field/results/{result_id}/next-review")
    def next_review(result_id: str):
        value = with_reviews(snapshot(result_id), store)
        return {
            "row": next(
                (r for r in value["rows"] if r["category"] != "OK" and not r["review"]), None
            ),
            "counts": value["counts"],
        }

    @app.post("/api/field/results/{result_id}/review", status_code=201)
    async def review(result_id: str, request: Request):
        value = await payload(request)
        row = next((r for r in snapshot(result_id)["rows"] if r["item"] == value.get("item")), None)
        if row is None:
            raise HTTPException(404, "確認対象がありません")
        try:
            return store.save(result_id, row, value)
        except FeedbackConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/field/results/{result_id}/download")
    async def download(result_id: str, request: Request):
        value = await payload(request, 8 * 1024 * 1024)
        try:
            data = await run_in_threadpool(
                export, with_reviews(snapshot(result_id), store), value.get("selected")
            )
            return Response(
                data,
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="period-results.csv"'},
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/field/results/{result_id}/issues-download")
    def issues_download(result_id: str):
        value = snapshot(result_id)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["原本値", "商品名", "理由", "原本行数", "確認状態"])
        for issue in value.get("input_issues", []):
            writer.writerow(
                [safe_csv(issue[k]) for k in ("source_value", "name", "reason", "rows", "status")]
            )
        return Response(output.getvalue().encode("utf-8-sig"), media_type="text/csv")

    @app.post("/api/field/results/{result_id}/export", status_code=201)
    async def prepare_export(result_id: str, request: Request):
        value = await payload(request, 8 * 1024 * 1024)
        try:
            if value.get("kind") == "issues":
                data = issues_download(result_id).body
            else:
                data = await run_in_threadpool(
                    export, with_reviews(snapshot(result_id), store), value.get("selected")
                )
            export_id = uuid.uuid4().hex
            (exports / f"{export_id}.csv").write_bytes(data)
            return {"download_href": f"/api/field/exports/{export_id}.csv"}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/field/exports/{export_id}.csv")
    def prepared_export(export_id: str):
        if not re.fullmatch(r"[0-9a-f]{32}", export_id):
            raise HTTPException(404)
        path = exports / f"{export_id}.csv"
        if not path.is_file():
            raise HTTPException(404, "出力ファイルがありません。もう一度作成してください")
        return FileResponse(path, filename="予測結果と担当者判断.csv", media_type="text/csv")

    @app.post("/api/field/feedback", status_code=201)
    async def feedback(request: Request):
        try:
            return store.feedback(await payload(request))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/field/events", status_code=201)
    async def event(request: Request):
        value = await payload(request)
        try:
            value["occurred_at"] = datetime.fromisoformat(value["occurred_at"])
            # Only UI observations here; confirmed judgments live in the server ledger.
            if value.get("event_name") not in {
                "STEP_VIEWED",
                "SOURCE_SELECTED",
                "ANALYSIS_REQUESTED",
            }:
                raise ValueError("記録できない画面操作です")
            events.append(make_operation_event(value, "portable-local-operator"))
            return {"saved": True}
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise HTTPException(422, "操作記録の形式を確認してください") from exc
