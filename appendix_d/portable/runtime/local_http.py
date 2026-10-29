"""Private loopback control traffic: no system proxy and no redirects."""

import json
import urllib.error
import urllib.request

MAX_RESPONSE_BYTES = 64 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Local redirect refused", headers, fp)


def request_json(port, path, *, token=None, method="GET", timeout=2):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("ローカル接続ポートを確認してください")
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path.startswith("//")
        or any(c in path for c in ("\r", "\n", "\\"))
    ):
        raise ValueError("ローカル接続先を確認してください")
    headers = {"X-Portable-Control": token} if token else {}
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", headers=headers, method=method
    )
    # Do not install globally: external AI/update/feedback traffic keeps its policy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("ローカルAPIの応答が大きすぎます")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("ローカルAPIのJSON応答を確認してください")
    return value
