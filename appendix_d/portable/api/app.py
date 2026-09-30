"""Local P1 UI and API. No production DB, external endpoints, or CDN."""

import hashlib
import json
import logging
import os
import re
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from forecast_provider.providers.builtin_baseline import PROVIDER_VERSION
from portable import APP_VERSION
from portable.runtime.paths import DataPaths

from .business_archive import (
    MAX_ZIP_BYTES,
    ArchiveError,
    analyze_archive,
    atomic_json,
    content_id,
    run_reference_backtest,
)
from .business_review import (
    ReviewError,
    apply_remembered_rules,
    decision_history,
    latest_decisions,
    rebuild_reviewed_prepared,
    record_decision,
    review_view,
)
from .forecast import forecast
from .input_csv import MAX_CSV_BYTES, InputError, parse_csv
from .store import RunStore

LOG = logging.getLogger("portable.api")
STATIC = Path(__file__).parent / "static"
SAMPLE = Path(__file__).resolve().parents[1] / "sample" / "synthetic_shipments.csv"


async def _read_limited(request: Request, limit: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise HTTPException(413, "アップロード容量が上限を超えています")
        body.extend(chunk)
    return bytes(body)


def create_app(data_root: Path, *, control_token: str | None = None) -> FastAPI:
    paths = DataPaths(data_root)
    paths.ensure()
    store = RunStore(paths.state / "runs.sqlite3")
    app = FastAPI(title="ブンセン Portable P1", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.state.active = 0
    app.state.closing = False
    app.state.lock = threading.Lock()

    def load_analysis(analysis_id: str) -> tuple[dict, Path]:
        if not re.fullmatch(r"[0-9a-f]{64}", analysis_id):
            raise HTTPException(404, "分析結果が見つかりません")
        report_path = paths.analysis / f"{analysis_id}.json"
        if not report_path.is_file():
            raise HTTPException(404, "分析結果が見つかりません")
        return json.loads(report_path.read_text(encoding="utf-8")), report_path

    def reviewed_report(report: dict) -> dict:
        journal = paths.decisions / f"{report['analysis_id']}.jsonl"
        return review_view(report, journal)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse({"detail": "localhostのみ利用できます"}, status_code=403)
        origin = request.headers.get("origin")
        expected = f"http://{request.headers.get('host', '')}"
        if origin and origin != expected:
            return JSONResponse({"detail": "外部ページから操作できません"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.get("/ready")
    def ready():
        return {"ready": not app.state.closing, "version": APP_VERSION}

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/app.js")
    def script():
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.get("/review.js")
    def review_script():
        return FileResponse(STATIC / "review.js", media_type="text/javascript")

    @app.get("/style.css")
    def style():
        return FileResponse(STATIC / "style.css", media_type="text/css")

    @app.get("/api/sample.csv")
    def sample_csv():
        return FileResponse(SAMPLE, media_type="text/csv")

    @app.get("/api/runs")
    def runs():
        return store.list()

    @app.get("/api/business-archives")
    def business_archives():
        records = []
        for report_path in sorted(
            paths.analysis.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
        )[:20]:
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            view = reviewed_report(report)
            records.append(
                {
                    "analysis_id": view.get("analysis_id"),
                    "status": view.get("status"),
                    "rows": view.get("rows"),
                    "products": view.get("products"),
                    "review": view.get("review"),
                }
            )
        return records

    @app.get("/api/business-archives/{analysis_id}")
    def business_archive(analysis_id: str):
        report, _ = load_analysis(analysis_id)
        return reviewed_report(report)

    @app.get("/api/business-archives/{analysis_id}/decision-history")
    def business_archive_decision_history(analysis_id: str):
        load_analysis(analysis_id)
        return decision_history(paths.decisions / f"{analysis_id}.jsonl")

    @app.post("/api/business-archives", status_code=201)
    async def create_business_archive(request: Request):
        if request.headers.get("content-type", "").split(";")[0] not in {
            "application/zip",
            "application/octet-stream",
        }:
            raise HTTPException(415, "在庫・出荷CSVを含むZIPを選択してください")
        data = await _read_limited(request, MAX_ZIP_BYTES)
        with app.state.lock:
            if app.state.closing:
                raise HTTPException(503, "終了処理中です")
            if app.state.active:
                raise HTTPException(409, "別の処理を実行中です")
            app.state.active += 1
        analysis_id = content_id(data)
        try:
            prepared_path = paths.prepared / f"{analysis_id}.csv"
            report = analyze_archive(data, prepared_path)
            input_path = paths.input / f"{analysis_id}.zip"
            if not input_path.exists():
                temporary = input_path.with_suffix(".tmp")
                temporary.write_bytes(data)
                os.replace(temporary, input_path)
            report = {
                "analysis_id": analysis_id,
                "input_sha256": analysis_id,
                **report,
            }
            atomic_json(paths.analysis / f"{analysis_id}.json", report)
            apply_remembered_rules(
                report,
                paths.decisions / f"{analysis_id}.jsonl",
                paths.decisions / "rules.jsonl",
            )
            if latest_decisions(paths.decisions / f"{analysis_id}.jsonl"):
                rebuild_reviewed_prepared(
                    prepared_path,
                    paths.prepared / f"{analysis_id}-reviewed.csv",
                    report,
                    paths.decisions / f"{analysis_id}.jsonl",
                )
            LOG.info("business_archive_analyzed analysis_id=%s", analysis_id)
            return reviewed_report(report)
        except ArchiveError as exc:
            LOG.info("business_archive_rejected code=PORTABLE-ARCHIVE-001")
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            LOG.exception("business_archive_failed code=PORTABLE-ARCHIVE-002")
            message = "分析できませんでした。エラーコード PORTABLE-ARCHIVE-002"
            raise HTTPException(500, message) from exc
        finally:
            with app.state.lock:
                app.state.active -= 1

    @app.post("/api/business-archives/{analysis_id}/issues/{issue_id}", status_code=201)
    async def decide_business_archive_issue(analysis_id: str, issue_id: str, request: Request):
        report, _ = load_analysis(analysis_id)
        if not re.fullmatch(r"[0-9a-f]{24}", issue_id):
            raise HTTPException(404, "確認対象が見つかりません")
        try:
            raw = await _read_limited(request, 8 * 1024)
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise ReviewError("判断内容を確認してください")
            with app.state.lock:
                if app.state.closing:
                    raise HTTPException(503, "終了処理中です")
                if app.state.active:
                    raise HTTPException(409, "別の処理を実行中です")
                app.state.active += 1
            try:
                record_decision(
                    report,
                    paths.decisions / f"{analysis_id}.jsonl",
                    paths.decisions / "rules.jsonl",
                    issue_id,
                    payload,
                )
                rebuild_reviewed_prepared(
                    paths.prepared / f"{analysis_id}.csv",
                    paths.prepared / f"{analysis_id}-reviewed.csv",
                    report,
                    paths.decisions / f"{analysis_id}.jsonl",
                )
                return reviewed_report(report)
            finally:
                with app.state.lock:
                    app.state.active -= 1
        except (ReviewError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/business-archives/{analysis_id}/backtest", status_code=201)
    def backtest_business_archive(analysis_id: str):
        report, report_path = load_analysis(analysis_id)
        reviewed_path = paths.prepared / f"{analysis_id}-reviewed.csv"
        prepared_path = (
            reviewed_path if reviewed_path.is_file() else paths.prepared / f"{analysis_id}.csv"
        )
        if not report_path.is_file() or not prepared_path.is_file():
            raise HTTPException(404, "分析結果が見つかりません")
        if not all(item["backtest_ready"] for item in report["center_windows"]):
            raise HTTPException(409, "直近35日のファイルが揃っていない拠点があります")
        with app.state.lock:
            if app.state.closing:
                raise HTTPException(503, "終了処理中です")
            if app.state.active:
                raise HTTPException(409, "別の処理を実行中です")
            app.state.active += 1
        try:
            result = run_reference_backtest(prepared_path, paths.state, analysis_id)
            atomic_json(paths.results / f"business-{analysis_id}.json", result)
            return result
        except Exception as exc:
            LOG.exception("business_backtest_failed analysis_id=%s", analysis_id)
            message = "参考評価に失敗しました。エラーコード PORTABLE-BACKTEST-001"
            raise HTTPException(500, message) from exc
        finally:
            with app.state.lock:
                app.state.active -= 1

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        record = store.get(run_id)
        if not record:
            raise HTTPException(404, "結果が見つかりません")
        if record["status"] == "SUCCESS":
            result_path = paths.results / f"{run_id}.json"
            if (
                not result_path.is_file()
                or hashlib.sha256(result_path.read_bytes()).hexdigest() != record["result_sha256"]
            ):
                raise HTTPException(500, "保存結果の整合性を確認できません")
            record["predictions"] = json.loads(result_path.read_text(encoding="utf-8"))
        return record

    @app.get("/api/runs/{run_id}/download")
    def download(run_id: str):
        record = store.get(run_id)
        if not record or record["status"] != "SUCCESS":
            raise HTTPException(404, "保存結果が見つかりません")
        result_path = paths.results / f"{run_id}.json"
        if (
            not result_path.is_file()
            or hashlib.sha256(result_path.read_bytes()).hexdigest() != record["result_sha256"]
        ):
            raise HTTPException(500, "保存結果の整合性を確認できません")
        return FileResponse(
            result_path, filename=f"bunsen-p1-{run_id}.json", media_type="application/json"
        )

    @app.post("/api/runs", status_code=201)
    async def create_run(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "text/csv":
            raise HTTPException(415, "CSVを選択してください")
        data = await request.body()
        if len(data) > MAX_CSV_BYTES:
            raise HTTPException(413, "CSVが大きすぎます")
        with app.state.lock:
            if app.state.closing:
                raise HTTPException(503, "終了処理中です")
            if app.state.active:
                raise HTTPException(409, "別の予測を処理中です")
            app.state.active += 1
        run_id = str(uuid.uuid4())
        input_sha = hashlib.sha256(data).hexdigest()
        try:
            store.start(run_id, input_sha, APP_VERSION, PROVIDER_VERSION)
            frame = parse_csv(data)
            input_path = paths.input / f"{run_id}.csv"
            input_path.write_bytes(data)
            LOG.info("baseline_started run_id=%s", run_id)
            predictions = forecast(frame, paths.state, run_id)
            result_bytes = json.dumps(
                predictions, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            result_sha = hashlib.sha256(result_bytes).hexdigest()
            temp = paths.results / f"{run_id}.tmp"
            result_path = paths.results / f"{run_id}.json"
            temp.write_bytes(result_bytes)
            os.replace(temp, result_path)
            store.finish(run_id, result_sha=result_sha, result_path=str(result_path))
            LOG.info("baseline_finished run_id=%s", run_id)
            return store.get(run_id) | {"predictions": predictions}
        except InputError as exc:
            LOG.info("input_rejected code=PORTABLE-INPUT-001")
            store.finish(run_id, error_code="PORTABLE-INPUT-001")
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            LOG.exception("baseline_failed run_id=%s code=PORTABLE-RUN-001", run_id)
            if store.get(run_id):
                store.finish(run_id, error_code="PORTABLE-RUN-001")
            raise HTTPException(500, "予測できませんでした。エラーコード PORTABLE-RUN-001") from exc
        finally:
            with app.state.lock:
                app.state.active -= 1

    @app.post("/api/control/drain")
    def drain(request: Request):
        if not control_token or request.headers.get("x-portable-control") != control_token:
            raise HTTPException(403, "操作できません")
        with app.state.lock:
            app.state.closing = True
            return {"active": app.state.active}

    @app.get("/api/control/status")
    def status(request: Request):
        if not control_token or request.headers.get("x-portable-control") != control_token:
            raise HTTPException(403, "操作できません")
        return {"active": app.state.active}

    return app
