"""終業時の署名済みUpdate Manifest確認。適用は行わない。"""

from __future__ import annotations

import base64
import json
import ssl
import urllib.request
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .transport import _NoRedirect


def _version(value: str) -> tuple[int, ...]:
    try:
        parts = tuple(int(piece) for piece in value.split("."))
    except ValueError as exc:
        raise ValueError("UPDATE_VERSION_INVALID") from exc
    if not 2 <= len(parts) <= 4 or any(piece < 0 for piece in parts):
        raise ValueError("UPDATE_VERSION_INVALID")
    return parts


def check_update(url: str, public_pem: bytes, current_version: str, *, fetcher=None) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("UPDATE_TLS_REQUIRED")
    if fetcher is None:
        def fetcher(address):
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            opener = urllib.request.build_opener(
                _NoRedirect, urllib.request.HTTPSHandler(context=context),
            )
            with opener.open(address, timeout=10) as response:
                return response.read(65_537)
    raw = fetcher(url)
    if len(raw) > 65_536:
        raise ValueError("UPDATE_MANIFEST_TOO_LARGE")
    document = json.loads(raw)
    if not isinstance(document, dict) or set(document) != {"manifest", "signature"}:
        raise ValueError("UPDATE_MANIFEST_INVALID")
    manifest = document["manifest"]
    if not isinstance(manifest, dict) or set(manifest) != {"version", "sha256", "artifact_url"}:
        raise ValueError("UPDATE_MANIFEST_INVALID")
    key = serialization.load_pem_public_key(public_pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("UPDATE_SIGNING_KEY_INVALID")
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    key.verify(base64.b64decode(document["signature"], validate=True), canonical)
    artifact = urlparse(manifest["artifact_url"])
    if (artifact.scheme != "https" or not artifact.hostname or artifact.username
            or artifact.password or len(manifest["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in manifest["sha256"])):
        raise ValueError("UPDATE_MANIFEST_INVALID")
    return {"available": _version(manifest["version"]) > _version(current_version),
            "version": manifest["version"]}
