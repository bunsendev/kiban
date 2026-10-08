"""Local document intake routes, isolated from automatic CSV approval."""

import json
from urllib.parse import unquote

from fastapi import HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from portable.runtime.api_credentials import CredentialError

from .document_ai import MAX_BYTES, DocumentError
from .document_intake import Documents
from .document_master import candidates, parse_master, sheets


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
            if action == "local":
                if type(value.get("retry", False)) is not bool:
                    raise DocumentError("再読取の指定を確認してください")
                return await run_in_threadpool(
                    service.read_local, identifier, value.get("retry", False)
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
                )
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
