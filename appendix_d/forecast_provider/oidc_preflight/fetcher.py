"""標準TLS検証を使う上限付きOIDC JSON取得。"""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .contracts import USER_AGENT, require_https_url


class FetchError(RuntimeError):
    """URLや応答本文を外へ漏らさない取得失敗。"""


@dataclass(frozen=True)
class JsonDocument:
    value: dict[str, Any]
    content_type: str
    elapsed_ms: int


class JsonFetcher(Protocol):
    def fetch(self, url: str) -> JsonDocument: ...


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpsJsonFetcher:
    def __init__(self, timeout_seconds: float, max_response_bytes: int) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        context = ssl.create_default_context()
        self._opener = build_opener(_RejectRedirects(), HTTPSHandler(context=context))

    def fetch(self, url: str) -> JsonDocument:
        require_https_url(url, "取得先")
        request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
        started = monotonic()
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                if response.geturl() != url or response.status != 200:
                    raise FetchError("OIDC metadata取得に失敗しました")
                raw = response.read(self.max_response_bytes + 1)
                content_type = response.headers.get_content_type()
        except FetchError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError) as exc:
            raise FetchError("OIDC metadata取得に失敗しました") from exc
        if len(raw) > self.max_response_bytes:
            raise FetchError("OIDC metadata応答が大きすぎます")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FetchError("OIDC metadata応答がJSONではありません") from exc
        if not isinstance(value, dict):
            raise FetchError("OIDC metadata応答がobjectではありません")
        return JsonDocument(value, content_type, round((monotonic() - started) * 1_000))
