"""Local document intake routes, isolated from automatic CSV approval."""

import io
import json
import zipfile
from urllib.parse import unquote

from fastapi import HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from portable.runtime.api_credentials import CredentialError

from .business_archive import MAX_ZIP_BYTES, _safe_members
from .document_ai import MAX_BYTES, DocumentError
from .document_intake import Documents
from .document_master import candidates, parse_master, sheets
from .document_suggestions import suggest_rows
from .exclusion_import import preview_list


def register_document_routes(app, paths, drop_folder):
    service = Documents(paths)
    app.state.documents = service

    async def body(request, maximum):
        result = bytearray()
        async for chunk in request.stream():
            result.extend(chunk)
            if len(result) > maximum:
                raise HTTPException(413, "容量が大きすぎます。文書を分割してください")
        return bytes(result)

    @app.get("/api/ai-settings")
    def ai_settings():
        return service.ai.summary()

    @app.post("/api/ai-settings")
    async def save_ai_settings(request: Request):
        try:
            service.ai.save(json.loads(await body(request, 32768)))
            return service.ai.summary()
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "モデル・為替・月間回数・予算を確認してください") from exc

    @app.get("/api/product-exclusions")
    def excluded_products():
        return service.exclusions.list()

    @app.post("/api/product-exclusions")
    async def save_excluded_products(request: Request):
        try:
            value = json.loads(await body(request, 1024 * 1024))
            return service.exclusions.save(value)
        except (DocumentError, ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(
                422, str(exc) if isinstance(exc, DocumentError) else "設定内容を確認してください"
            ) from None

    @app.post("/api/product-exclusions/preview")
    async def preview_exclusions(request: Request):
        try:
            raw = await body(request, MAX_BYTES)
            name = unquote(request.headers.get("x-file-name", ""))
            version = request.headers.get("x-master-version", "")
            master = None
            if version:
                with service.db() as db:
                    stored = db.execute(
                        "SELECT contents FROM document_masters WHERE version=?", (version,)
                    ).fetchone()
                if not stored:
                    raise DocumentError("登録済みマスター版を選んでください")
                master = json.loads(stored[0])
            result = await run_in_threadpool(
                lambda: preview_list(
                    raw,
                    name,
                    paths,
                    consent=request.headers.get("x-ai-consent") == "true",
                    master=master,
                )
            )
            service.exclusions.record_preview(raw, result)
            return result
        except (DocumentError, CredentialError) as exc:
            raise HTTPException(422, str(exc)) from None
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(422, "ファイルの内容を確認してください") from exc

    @app.post("/api/product-exclusions/import")
    async def import_excluded_products(request: Request):
        try:
            return service.exclusions.import_file(await body(request, 1024 * 1024))
        except DocumentError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/api/documents")
    def documents():
        return service.list()

    @app.post("/api/documents/upload")
    async def upload_document(request: Request):
        raw = await body(request, MAX_BYTES)
        try:
            return service.add(unquote(request.headers.get("x-file-name", "document")), raw)
        except DocumentError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/api/documents/folder")
    def scan_documents():
        count = 0
        for path in sorted(paths.incoming.iterdir()):
            if path.suffix.lower() not in (".pdf", ".png", ".jpg", ".jpeg"):
                continue
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
                continue
            try:
                service.add(path.name, path.read_bytes())
                count += 1
            except (DocumentError, OSError):
                continue
        return {"count": count}

    @app.post("/api/documents/batch")
    async def upload_document_batch(request: Request):
        raw = await body(request, MAX_ZIP_BYTES)
        accepted, errors = [], []
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = _safe_members(archive)
                for member in members:
                    if member.is_dir():
                        continue
                    if not member.filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
                        errors.append({"file": member.filename,
                                       "reason": "文書の一括登録はPDF・画像のみです"})
                        continue
                    if member.file_size > MAX_BYTES:
                        errors.append({"file": member.filename,
                                       "reason": "1ファイル10 MBを超えています"})
                        continue
                    try:
                        result = service.add(member.filename, archive.read(member))
                        accepted.append({"file": member.filename, "id": result["id"]})
                    except (ValueError, OSError) as exc:
                        errors.append({"file": member.filename, "reason": str(exc)})
        except (zipfile.BadZipFile, ValueError) as exc:
            raise HTTPException(422, str(exc)) from None
        return {"accepted": accepted, "errors": errors,
                "notice": "登録のみ。読取・原本確認・正式採用は別です。成功分は保持します"}

    @app.post("/api/document-master")
    async def import_master(request: Request):
        raw = await body(request, MAX_BYTES)
        try:
            sheet = unquote(request.headers.get("x-master-sheet", ""))
            if not sheet:
                return {"sheets": sheets(raw)}
            value = parse_master(raw, sheet, request.headers.get("x-effective-date", ""))
            with service.db() as db:
                db.execute(
                    "INSERT OR IGNORE INTO document_masters VALUES(?,?)",
                    (value["version"], json.dumps(value, ensure_ascii=False)),
                )
            return {k: v for k, v in value.items() if k != "products"} | {
                "count": len(value["products"])
            }
        except DocumentError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/api/document-master/suggest-rows")
    async def suggest_products(request: Request):
        try:
            value = json.loads(await body(request, 2 * 1024 * 1024))
            rows = value.get("rows")
            if (
                not isinstance(rows, list)
                or len(rows) > 1000
                or not all(isinstance(r, dict) for r in rows)
            ):
                raise DocumentError("確認一覧は1000行以内で選んでください")
            with service.db() as db:
                stored = db.execute(
                    "SELECT contents FROM document_masters WHERE version=?", (value.get("version"),)
                ).fetchone()
                approvals = db.execute(
                    "SELECT approval FROM documents WHERE approval IS NOT NULL "
                    "ORDER BY created DESC LIMIT 100"
                ).fetchall()
            if not stored:
                raise DocumentError("照合に使うマスター版を選んでください")
            master = json.loads(stored[0])
            prior = [r for item in approvals for r in json.loads(item[0])["rows"]]
            return {"rows": suggest_rows(rows, master, prior)}
        except (DocumentError, ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(
                422, str(exc) if isinstance(exc, DocumentError) else "入力内容を確認してください"
            ) from None

    @app.get("/api/document-master")
    def masters():
        with service.db() as db:
            values = [
                json.loads(r[0])
                for r in db.execute("SELECT contents FROM document_masters ORDER BY rowid DESC")
            ]
        return [
            {k: v for k, v in item.items() if k != "products"} | {"count": len(item["products"])}
            for item in values
        ]

    @app.post("/api/document-master/candidates")
    async def master_candidates(request: Request):
        try:
            value = json.loads(await body(request, 4096))
            with service.db() as db:
                stored = db.execute(
                    "SELECT contents FROM document_masters WHERE version=?", (value.get("version"),)
                ).fetchone()
            if not stored or not isinstance(value.get("row"), dict):
                raise DocumentError("登録済みのマスター版を選んでください")
            return {"candidates": candidates(json.loads(stored[0]), value["row"])}
        except (DocumentError, ValueError, TypeError, AttributeError) as exc:
            message = str(exc) if isinstance(exc, DocumentError) else "入力内容を確認してください"
            raise HTTPException(422, message) from None

    @app.get("/api/documents/{identifier}/history")
    def history(identifier: str):
        try:
            return service.history(identifier)
        except DocumentError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.get("/api/documents/{identifier}/original")
    def original(identifier: str):
        try:
            raw, mime = service.get(identifier, original=True)
            return Response(
                raw,
                media_type=mime,
                headers={
                    "Content-Security-Policy": "sandbox; default-src 'none'",
                    "Content-Disposition": "inline",
                },
            )
        except DocumentError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.post("/api/documents/{identifier}/{action}")
    async def act(identifier: str, action: str, request: Request):
        try:
            value = json.loads(await body(request, 2 * 1024 * 1024))
            if not isinstance(value, dict):
                raise DocumentError("入力内容を確認してください")
            if action in {"cancel", "resume"}:
                return await run_in_threadpool(
                    service.set_cancelled, identifier, action == "cancel"
                )
            if action == "local":
                if type(value.get("retry", False)) is not bool:
                    raise DocumentError("再読取の指定を確認してください")
                if type(value.get("blank_current_zero", False)) is not bool:
                    raise DocumentError("現在欄の空欄ルールを確認してください")
                return await run_in_threadpool(
                    service.read_local,
                    identifier,
                    value.get("retry", False),
                    value.get("blank_current_zero", False),
                )
            if action == "extract":
                if value.get("retry", False) not in (False, True):
                    raise DocumentError("再読取の指定を確認してください")
                return await run_in_threadpool(
                    service.read,
                    identifier,
                    value.get("consent"),
                    value.get("retry", False),
                    value.get("page"),
                    value.get("layout", "whole"),
                    value.get("master_version", ""),
                )
            if action == "correction":
                with drop_folder._lock:
                    return service.correction(identifier, value)
            if action == "draft":
                return await run_in_threadpool(service.save_draft, identifier, value)
            if action == "approve":
                return await run_in_threadpool(service.approve, identifier, value)
            if action == "dispatch":
                with drop_folder._lock:
                    return service.dispatch(identifier)
            raise HTTPException(404)
        except (DocumentError, CredentialError) as exc:
            raise HTTPException(422, str(exc)) from None
        except (ValueError, TypeError):
            raise HTTPException(422, "入力内容を確認してください") from None
