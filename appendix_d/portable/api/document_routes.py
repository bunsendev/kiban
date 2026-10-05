"""Local document intake routes, isolated from automatic CSV approval."""

import json
from urllib.parse import unquote

from fastapi import HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from portable.runtime.api_credentials import CredentialError

from .document_ai import MAX_BYTES, DocumentError
from .document_intake import Documents


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
            if action == "extract":
                return await run_in_threadpool(service.read, identifier, value.get("consent"))
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
