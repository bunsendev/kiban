"""Local field UI endpoints; business services remain the source of truth."""

import csv
import hashlib
import io
import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from forecast_provider.operation_events.domain import make_operation_event
from forecast_provider.operation_events.store import SqliteOperationEventStore
from portable.runtime.feedback_admin import authorized

from .business_archive import MAX_ZIP_BYTES, atomic_json
from .field_read_model import (
    build_saved_view,
    build_view,
    export,
    page,
    safe_csv,
    warehouse_scope,
    with_reviews,
)
from .field_store import FieldStore
from .field_workflow import FieldWorkflow
from .reference_demand import demand_forecast
from .result_feedback import FeedbackConflict

STATIC = Path(__file__).parent / "static" / "field"


def register_field_routes(app, paths, intake, daily, resolve, read_limited):
    @contextmanager
    def exclusive():
        with app.state.lock:
            if app.state.closing or app.state.active:
                raise HTTPException(409, "別の処理を実行中です。完了後に再試行してください")
            app.state.active += 1
        try:
            yield
        finally:
            with app.state.lock:
                app.state.active -= 1

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

    @app.post("/api/field/{analysis_id}/demand")
    async def demand_only(analysis_id: str, request: Request):
        if not re.fullmatch(r"[0-9a-f]{64}", analysis_id):
            raise HTTPException(422, "分析を確認してください")
        value = await payload(request)
        try:
            with exclusive():
                return await run_in_threadpool(demand_forecast, paths, analysis_id, value)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/api/field/input-history/rebuild")
    def rebuild_input_history():
        accepted, errors = [], []
        originals = sorted(paths.input.glob('*.zip'), key=lambda p: p.stat().st_mtime_ns)
        with exclusive():
            for digest in intake.history.original_ids():
                try:
                    result = intake.ingest(intake.history.original_bytes(digest))
                    accepted.append({'source':digest[:16]+'（受付原本）',
                                     'analysis_id':result['analysis_id']})
                except ValueError as exc:
                    errors.append({'source':digest[:16], 'reason':str(exc)})
            for source in originals:
                try:
                    result = intake.ingest(source.read_bytes())
                    accepted.append({'source':source.name,'analysis_id':result['analysis_id']})
                except ValueError as exc:
                    errors.append({'source':source.name,'reason':str(exc)})
        return {'accepted':accepted, 'errors':errors,
                'notice':'以前の原本を候補履歴へ再集計しました。正式承認は変更していません。'}

    @app.get("/api/field/saved-forecasts/{reference}/results")
    def saved_result(reference: str):
        try:
            app.state.saved_forecasts.manifest(reference)
            for path in sorted(snapshots.glob("*.json"), reverse=True):
                try:
                    value = snapshot(path.stem)
                except HTTPException:
                    continue
                if value.get("build_id") == reference:
                    return {"result_id": value["result_id"]}
            value = build_saved_view(daily, reference, resolve, app.state.saved_forecasts)
            atomic_json(snapshots / f"{value['result_id']}.json", value)
            return {"result_id": value["result_id"]}
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

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
        value = snapshot(result_id)
        try:
            scoped = warehouse_scope(value, warehouse)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return page(with_reviews(scoped, store), q, "", attention, offset, limit) | {
            "warehouses": sorted({r["warehouse"] for r in value["rows"]})
        }

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
            exceptional = value.get("exceptional") is True
            if exceptional and not authorized(paths, request.headers.get("x-feedback-admin", "")):
                raise HTTPException(403, "例外修正にはWindows管理者の一時認証が必要です")
            return store.save(result_id, row, value, exceptional=exceptional)
        except FeedbackConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/field/results/{result_id}/download")
    async def download(result_id: str, request: Request):
        value = await payload(request, 8 * 1024 * 1024)
        try:
            scoped = warehouse_scope(snapshot(result_id), value.get("warehouse", ""))
            data = await run_in_threadpool(
                export, with_reviews(scoped, store), value.get("selected")
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
                scoped = warehouse_scope(snapshot(result_id), value.get("warehouse", ""))
                data = await run_in_threadpool(
                    export, with_reviews(scoped, store), value.get("selected")
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
