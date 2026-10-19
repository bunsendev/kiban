"""Managed history-study inputs; no arbitrary local paths or automatic adoption."""

import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from portable.history_import import read_history_archive
from portable.history_study import backtest, save

from .business_archive import MAX_ZIP_BYTES
from .formal_forecast_pipeline import PortableFormalForecastPipeline
from .product_exclusions import ProductExclusions


def register_history_studies(app, paths, read_limited):
    root = paths.state / "HistoryStudies"
    root.mkdir(exist_ok=True)
    pipeline = PortableFormalForecastPipeline(paths)

    def read(study_id):
        if not re.fullmatch("[0-9a-f]{64}", study_id):
            raise ValueError("比較履歴IDが不正です")
        value = json.loads((root / (study_id + ".json")).read_text("utf-8"))
        body = {k: v for k, v in value.items() if k != "result_sha256"}
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        ).hexdigest()
        if digest != value.get("result_sha256") or value.get("study_id") != study_id:
            raise ValueError("比較履歴の整合性を確認できません")
        return value

    @app.get("/history-studies")
    def screen():
        return FileResponse(Path(__file__).parent / "static/field/history.html")

    @app.get("/api/history-studies")
    def overview():
        studies = []
        for p in sorted(root.glob("*.json"), reverse=True):
            try:
                v = read(p.stem)
                studies.append(
                    {
                        "study_id": p.stem,
                        "created_at": v["created_at"],
                        "series": len(v["quality"]),
                        "unit_confirmed": v["settings"]["unit_confirmed"],
                    }
                )
            except (ValueError, OSError, KeyError):
                continue
        builds = []
        for p in sorted(paths.formal_forecast.glob("portable-daily-*/manifest.json")):
            try:
                v = pipeline._verified_result(p)
                builds.append(
                    {
                        "build_id": v["build_id"],
                        "train_start": v["train_start"],
                        "train_end": v["train_end"],
                    }
                )
            except (ValueError, OSError, KeyError):
                continue
        return {"studies": studies, "builds": builds, "production_changed": False}

    @app.get("/api/history-studies/{study_id}")
    def result(study_id: str, offset: int = 0, limit: int = 100):
        if offset < 0 or limit < 1 or limit > 1000:
            raise HTTPException(422, "表示範囲を確認してください")
        try:
            value = read(study_id)
            rows = value.pop("rows")
            return value | {"rows": rows[offset : offset + limit], "row_count": len(rows)}
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/history-studies", status_code=201)
    async def create(request: Request):
        try:
            payload = json.loads(await read_limited(request, 4096))
            if not isinstance(payload, dict):
                raise ValueError("入力内容を確認してください")
            build_id = str(payload.get("build_id") or "")
            if not re.fullmatch("portable-daily-[0-9a-f]{64}", build_id):
                raise ValueError("日次buildを選んでください")
            if payload.get("confirm_retrospective_availability_assumption") is not True:
                raise ValueError("過去の利用可能日時が不明な場合に日次末を仮定する確認が必要です")
            pipeline.result_path(build_id)
            manifest = pipeline._verified_result(paths.formal_forecast / build_id / "manifest.json")
            raw = (paths.formal_forecast / build_id / "daily.csv").read_bytes()
            records = [
                {
                    "unique_id": r["unique_id"],
                    "ds": r["ds"],
                    "y": r["y"],
                    "unit": "CASE",
                    "known_at": r["ds"] + "T23:59:59+09:00",
                }
                for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
                if r["state"] in {"OBSERVED", "CONFIRMED_ZERO"}
            ]
            if not records:
                raise ValueError("確認済みの出荷実績がありません")
            with app.state.lock:
                if app.state.active or app.state.closing:
                    raise HTTPException(409, "別の処理を実行中です")
                app.state.active += 1
            try:
                value = await run_in_threadpool(
                    backtest,
                    pd.DataFrame(records),
                    unit_confirmed=True,
                    provenance={
                        "build_id": build_id,
                        "source_daily_sha256": manifest["daily_data_sha256"],
                        "availability_mode": "DAILY_END_ASSUMED",
                        "formal_adoption": False,
                    },
                )
                await run_in_threadpool(save, value, root)
                return {"study_id": value["study_id"], "production_changed": False}
            finally:
                with app.state.lock:
                    app.state.active -= 1
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/history-studies/upload", status_code=201)
    async def upload(request: Request):
        if request.headers.get("x-history-availability-confirmed") != "true":
            raise HTTPException(422, "ファイル日付を利用可能日時とする仮定の確認が必要です")
        if (
            request.headers.get("x-history-unit", "UNCONFIRMED") == "UNCONFIRMED"
            and request.headers.get("x-history-unit-assumption-confirmed") != "true"
        ):
            raise HTTPException(422, "単位未確認での参考集計に関する仮定を確認してください")
        raw = await read_limited(request, MAX_ZIP_BYTES)
        unit = request.headers.get("x-history-unit", "UNCONFIRMED")
        with app.state.lock:
            if app.state.active or app.state.closing:
                raise HTTPException(409, "別の処理を実行中です")
            app.state.active += 1
        try:
            # Preserve source independently of forecasts and formal operational actuals.
            source = paths.state / "HistorySources"
            source.mkdir(exist_ok=True)
            digest = hashlib.sha256(raw).hexdigest()
            original = source / (digest + ".zip")
            if not original.exists():
                original.write_bytes(raw)
            rules = ProductExclusions(paths).list()
            excluded = {
                r["jan"] for r in rules if r.get("exclude") and r.get("match_type") != "prefix"
            }
            excluded_prefixes = [
                r["jan"] for r in rules if r.get("exclude") and r.get("match_type") == "prefix"
            ]
            frame, provenance = await run_in_threadpool(
                read_history_archive,
                raw,
                unit=unit,
                excluded_jans=excluded,
                excluded_prefixes=[p for p in excluded_prefixes if p],
            )
            value = await run_in_threadpool(
                backtest,
                frame,
                unit_confirmed=provenance["unit_confirmed"],
                provenance=provenance,
                allow_unconfirmed_units=request.headers.get("x-history-unit-assumption-confirmed")
                == "true",
            )
            await run_in_threadpool(save, value, root)
            return {"study_id": value["study_id"], "production_changed": False}
        except (ValueError, OSError, KeyError, zipfile.BadZipFile, csv.Error) as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            with app.state.lock:
                app.state.active -= 1
