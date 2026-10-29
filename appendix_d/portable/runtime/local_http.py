"""Private loopback control traffic: no system proxy and no redirects."""

import http.client
import json
import urllib.error

MAX_RESPONSE_BYTES = 64 * 1024


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
    connection = None
    phase = "HTTP_INIT"
    try:
        # urllib.build_opener creates an HTTPS handler/SSL context even for HTTP.
        # A missing certificate-store/keylog file can then fail before connecting.
        # A fixed HTTPConnection never initializes TLS, consults proxies or redirects.
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        connection.set_debuglevel(0)
        phase = "HTTP_REQUEST"
        connection.request(method, path, headers=headers)
        phase = "HTTP_RESPONSE"
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            reason = (
                "Local redirect refused" if 300 <= response.status < 400 else "Local HTTP error"
            )
            raise urllib.error.HTTPError(
                f"http://127.0.0.1:{port}{path}", response.status, reason, response.headers, None
            )
        phase = "HTTP_BODY"
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("ローカルAPIの応答が大きすぎます")
        phase = "JSON_RESPONSE"
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("ローカルAPIのJSON応答を確認してください")
        return value
    except (OSError, ValueError, http.client.HTTPException) as exc:
        if isinstance(exc, http.client.HTTPException) and not isinstance(exc, OSError):
            error = ValueError("ローカルAPIのHTTP応答を確認できません")
            error.portable_local_phase = phase
            raise error from exc
        exc.portable_local_phase = phase
        raise
    finally:
        if connection is not None:
            connection.close()
