"""認証情報を記録せずローカル検証APIを呼び出す小さなHTTP client。"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


class AcceptanceHttpError(RuntimeError):
    """受入APIとの通信または応答が不正。"""


class AcceptanceClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0) -> None:
        self.base_url = _safe_base_url(base_url)
        if not token:
            raise ValueError("tokenが設定されていません")
        self._token = token
        self.timeout = timeout

    def get(self, path: str) -> Any:
        return self._request(path, method="GET")

    def post(self, path: str, payload: dict[str, object]) -> Any:
        return self._request(path, method="POST", payload=payload)

    def job(self, job_id: str) -> dict[str, Any]:
        return self.get(f"/api/mapping-dry-run-jobs/{quote(job_id, safe='')}")

    def report(self, report_sha256: str) -> dict[str, Any]:
        return self.get(f"/api/mapping-dry-runs/{quote(report_sha256, safe='')}")

    def _request(
        self,
        path: str,
        *,
        method: str,
        payload: dict[str, object] | None = None,
    ) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise AcceptanceHttpError(f"APIがHTTP {exc.code}を返しました: {path}") from exc
        except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AcceptanceHttpError(f"APIへ接続または応答を解釈できません: {path}") from exc


def _safe_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path:
        raise ValueError("base URLはhttp(s)のoriginを指定してください")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("平文HTTPはloopbackだけに使用できます")
    return normalized
