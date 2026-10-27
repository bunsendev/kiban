"""Local quality read models and admin-only, versioned configuration."""

import json

from fastapi import HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from portable.runtime.feedback_admin import authorized

from .data_quality import LABELS


def register_data_quality_routes(app, paths, service, read_limited, daily):
    def summary(analysis_id):
        value = service.summary(service.check(analysis_id))
        # Preview the actual assigned model when inventory registration already exists.
        state = daily.view(analysis_id)
        if state.get("registration_id"):
            registration = daily.pipeline.get_registration(state["registration_id"])
            from .runtime_assignments import PortableRuntimeAssignments
            from .runtime_profiles import BASELINE_CONFIGURATION

            scopes = [
                daily.pipeline.inventory_store.get_job(j["job_id"]).pilot_scope_version
                for j in registration["jobs"]
            ]
            resolutions = PortableRuntimeAssignments(paths).preview_scopes(scopes)
            if any(
                r["status"] != "BASELINE_SELECTED"
                or r["selected_configuration"] != BASELINE_CONFIGURATION
                for r in resolutions
            ):
                value["methods"]["C"] = {
                    "enabled": False,
                    "reason": "このPilot Scopeで選択されたモデルはC方式に未対応です",
                }
        return value | {"labels": LABELS}

    @app.get("/api/data-quality/rules")
    def rules():
        return service.rules()

    @app.post("/api/data-quality/rules", status_code=201)
    async def save_rules(request: Request):
        if not authorized(paths, request.headers.get("x-feedback-admin", "")):
            raise HTTPException(403, "品質設定の変更にはWindows管理者の一時認証が必要です")
        try:
            value = json.loads(await read_limited(request, 2 * 1024 * 1024))
            return service.save_rules(value)
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(
                422, str(exc) if isinstance(exc, ValueError) else "品質設定の形式を確認してください"
            ) from None

    @app.get("/api/business-archives/{analysis_id}/data-quality")
    def get_check(analysis_id: str):
        try:
            return summary(analysis_id)
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, "取込データと品質検証を再確認してください") from exc

    @app.post("/api/business-archives/{analysis_id}/data-quality")
    async def recheck(analysis_id: str):
        try:
            with app.state.lock:
                if app.state.active or app.state.closing:
                    raise HTTPException(409, "別の処理を実行中です。完了後に再確認してください")
            return await run_in_threadpool(summary, analysis_id)
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, "取込データと品質検証を再確認してください") from exc

    @app.get("/api/data-quality/{check_id}/issues")
    def issues(
        check_id: str,
        warehouse: str = "",
        jan: str = "",
        day: str = "",
        code: str = "",
        state: str = "",
        group: bool = False,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ):
        try:
            check = service.store.get("check", check_id)
            service.check(check["analysis_id"])
            latest = service.latest_covering(check)
            index = service.resolution_index(latest)
            series = {(s["warehouse"], s["jan"]): s for s in check["series"]}
            rows = []
            for r in check["issues"]:
                item = series.get((r["warehouse"], r["jan"]), {})
                impact = (
                    "通常予測の条件を満たしています"
                    if item.get("normal_eligible") else
                    "通常予測の前に補充・確認／対応モデルなら暫定予測可能"
                    if item.get("provisional_eligible") else
                    "補充・確認してから予測条件を再確認してください"
                )
                rows.append(r | {"state": service.issue_state(r, index), "impact": impact})
            rows = [
                r
                for r in rows
                if (not warehouse or r["warehouse"] == warehouse)
                and (not jan or jan.casefold() in (r["jan"] + " " + r["product_name"]).casefold())
                and (not day or r["date"] == day)
                and (not code or r["code"] == code)
                and (not state or r["state"] == state)
            ]
            if group:
                grouped = {}
                for r in rows:
                    key = (r["date"], r["warehouse"], r["state"])
                    item = grouped.setdefault(
                        key,
                        {
                            "date": key[0],
                            "warehouse": key[1],
                            "state": key[2],
                            "products": set(),
                            "codes": set(),
                            "impacts": set(),
                        },
                    )
                    if r["jan"]:
                        item["products"].add(r["jan"])
                    item["codes"].add(r["code"])
                    item["impacts"].add(r["impact"])
                rows = [
                    r | {"products": len(r["products"]), "codes": sorted(r["codes"]),
                         "impacts": sorted(r["impacts"])}
                    for _, r in sorted(grouped.items())
                ]
            return {
                "items": rows[offset : offset + limit],
                "total": len(rows),
                "latest_check_id": latest["id"],
                "check_id": check_id,
            }
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(404, "品質検証履歴を確認してください") from exc

    @app.get("/api/business-archives/{analysis_id}/data-quality/history")
    def history(analysis_id: str):
        try:
            service.check(analysis_id)
            return {
                "checks": [service.summary(c) for c in service.store.list("check", analysis_id)],
                "executions": service.store.list("execution", analysis_id),
                "receipts": service.store.list("receipt", analysis_id),
            }
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(404, "検証履歴を確認してください") from exc
