"""HTTP boundary for Portable formal inventory handoff packages."""

import json
import re
import zipfile

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from .inventory_handoff import (
    InventoryHandoffError,
    build_inventory_handoff,
    inventory_centers,
)


def register_inventory_handoff_routes(app, paths, load_analysis, read_limited) -> None:
    @app.get("/api/business-archives/{analysis_id}/formal-inventory")
    def formal_inventory_view(analysis_id: str):
        report, _ = load_analysis(analysis_id)
        archive_path = paths.input / f"{analysis_id}.zip"
        if not archive_path.is_file():
            raise HTTPException(404, "原本ZIPが見つかりません")
        handoffs = []
        for manifest_path in paths.formal_inventory.glob("*/manifest.json"):
            try:
                item = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if item.get("analysis_id") == report["analysis_id"]:
                handoffs.append(item)
        handoffs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return {
            "centers": inventory_centers(archive_path),
            "latest": handoffs[0] if handoffs else None,
        }

    @app.post("/api/business-archives/{analysis_id}/formal-inventory", status_code=201)
    async def create_formal_inventory_handoff(analysis_id: str, request: Request):
        report, _ = load_analysis(analysis_id)
        try:
            raw = await read_limited(request, 32 * 1024)
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                raise InventoryHandoffError("正式在庫の確認内容を確認してください")
            with app.state.lock:
                if app.state.closing:
                    raise HTTPException(503, "終了処理中です")
                if app.state.active:
                    raise HTTPException(409, "別の処理を実行中です")
                app.state.active += 1
            try:
                return build_inventory_handoff(
                    paths.input / f"{analysis_id}.zip",
                    report,
                    paths.decisions / f"{analysis_id}.jsonl",
                    paths.formal_inventory,
                    payload,
                )
            finally:
                with app.state.lock:
                    app.state.active -= 1
        except (InventoryHandoffError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/formal-inventory/{handoff_id}/download")
    def download_formal_inventory(handoff_id: str):
        if not re.fullmatch(r"[0-9a-f]{64}", handoff_id):
            raise HTTPException(404, "正式在庫パッケージが見つかりません")
        path = paths.formal_inventory / f"{handoff_id}.zip"
        if not path.is_file():
            raise HTTPException(404, "正式在庫パッケージが見つかりません")
        return FileResponse(
            path,
            filename=f"formal-inventory-{handoff_id[:12]}.zip",
            media_type="application/zip",
        )
