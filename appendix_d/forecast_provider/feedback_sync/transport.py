"""TLS送信とOutboxの再送。通信失敗はローカル処理を止めない。"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .policy import FeedbackStore


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def upload(url: str, token: str, envelope: bytes, *, timeout: int = 15) -> dict:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or parsed.query):
        raise ValueError("FEEDBACK_TLS_ENDPOINT_REQUIRED")
    if not token or len(token) < 32:
        raise ValueError("FEEDBACK_CREDENTIAL_REQUIRED")
    request = urllib.request.Request(
        url, data=envelope, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout) as response:
        return json.loads(response.read(4096))


def send_pending(store: FeedbackStore, *, url: str, token: str,
                 sender=upload) -> dict:
    store.recover_uploading()
    result = {"sent": 0, "retryable": 0, "rejected": 0}
    for item in store.pending():
        package_id = item["package_id"]
        if hashlib.sha256(item["envelope"]).hexdigest() != item["sha256"]:
            store.mark(package_id, "REJECTED", "LOCAL_HASH_MISMATCH")
            result["rejected"] += 1
            continue
        store.mark(package_id, "UPLOADING")
        try:
            response = sender(url, token, item["envelope"])
            if response.get("package_id") != package_id or response.get("status") not in {
                "ACCEPTED", "DUPLICATE",
            }:
                raise ValueError("FEEDBACK_ACK_INVALID")
        except urllib.error.HTTPError as exc:
            retry = exc.code == 429 or exc.code >= 500
            store.mark(package_id, "FAILED_RETRYABLE" if retry else "REJECTED",
                       f"HTTP_{exc.code}")
            result["retryable" if retry else "rejected"] += 1
        except (OSError, ValueError, TimeoutError):
            store.mark(package_id, "FAILED_RETRYABLE", "NETWORK_OR_ACK_ERROR")
            result["retryable"] += 1
        else:
            store.mark(package_id, "SENT")
            result["sent"] += 1
    return result
