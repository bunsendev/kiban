"""Feedback送信契約。HTTP実装を業務ロジックから分離する。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from .policy import FeedbackStore


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _endpoint(url: str, token: str) -> None:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or parsed.query):
        raise ValueError("FEEDBACK_TLS_ENDPOINT_REQUIRED")
    if not token or len(token) < 32 or "\r" in token or "\n" in token:
        raise ValueError("FEEDBACK_CREDENTIAL_REQUIRED")


def privacy_header(item: dict) -> str:
    """Serialize the receiver contract; never assert absent business data by default."""
    policy = item["policy_version"]
    fields = {"contains_raw_files", "contains_jan", "contains_product_names",
              "contains_customer_names"}
    value = item.get("privacy_manifest")
    if value is None:
        # Older encrypted outbox entries carry no inspectable content declaration.
        # Conservatively flag unknown contents instead of declaring them absent.
        value = {"policy_version": policy, **dict.fromkeys(fields, True)}
    if (not isinstance(value, dict) or set(value) != fields | {"policy_version"}
            or value["policy_version"] != policy
            or any(type(value[k]) is not bool for k in fields)):
        raise ValueError("FEEDBACK_PRIVACY_HEADER_INVALID")
    return base64.b64encode(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).decode("ascii")


class FeedbackTransport(Protocol):
    def send(self, item: dict, token: str) -> dict: ...


def _post(request: urllib.request.Request, timeout: int) -> dict:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(_NoRedirect,
                                         urllib.request.HTTPSHandler(context=context))
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(4097)
    if len(raw) > 4096:
        raise ValueError("FEEDBACK_ACK_TOO_LARGE")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("FEEDBACK_ACK_INVALID")
    return result


@dataclass(frozen=True)
class FutureFeedbackApiTransport:
    """PR #109の中央FastAPI契約。後方互換用。"""

    url: str
    timeout: int = 15
    kind: str = "api"

    def send(self, item: dict, token: str) -> dict:
        _endpoint(self.url, token)
        request = urllib.request.Request(
            self.url, data=item["envelope"], method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json", "Accept": "application/json"},
        )
        return _post(request, self.timeout)


@dataclass(frozen=True)
class SharedServerTransport:
    """Pilot共有サーバーupload.phpのoctet-stream契約。"""

    url: str
    client_id: str
    timeout: int = 15
    kind: str = "shared_php"

    def send(self, item: dict, token: str) -> dict:
        _endpoint(self.url, token)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.client_id):
            raise ValueError("FEEDBACK_CLIENT_INVALID")
        package_id = item["package_id"]
        if not re.fullmatch(r"[0-9a-f]{32}", package_id):
            raise ValueError("FEEDBACK_REQUEST_ID_INVALID")
        digest = hashlib.sha256(item["envelope"]).hexdigest()
        if digest != item["sha256"]:
            raise ValueError("FEEDBACK_LOCAL_HASH_MISMATCH")
        privacy = item["policy_version"]
        if not isinstance(privacy, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", privacy):
            raise ValueError("FEEDBACK_PRIVACY_HEADER_INVALID")
        request = urllib.request.Request(
            self.url, data=item["envelope"], method="POST", headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "Accept": "application/json",
                "X-Bunsen-Client": self.client_id,
                "X-Bunsen-Request-Id": package_id,
                "X-Bunsen-Sha256": digest,
                "X-Bunsen-Privacy": privacy_header(item),
            },
        )
        permanent_codes = {"AUTH_FAILED", "CLIENT_NOT_ALLOWED", "KEY_INVALID",
                           "KEY_NOT_FOUND", "PRIVACY_REJECTED"}
        try:
            response = _post(request, self.timeout)
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(4097)
                error = json.loads(body).get("error") if len(body) <= 4096 else None
                if isinstance(error, str) and error in permanent_codes:
                    raise ValueError(error) from None
            except (json.JSONDecodeError, UnicodeError, AttributeError, TypeError):
                pass
            raise
        if isinstance(response.get("error"), str) and response["error"] in permanent_codes:
            raise ValueError(response["error"])
        if response.get("ok") is not True or response.get("status") not in {
            "RECEIVED", "DUPLICATE", "ALREADY_RECEIVED",
        }:
            raise ValueError("FEEDBACK_ACK_REJECTED")
        if response.get("request_id") != package_id:
            raise ValueError("FEEDBACK_ACK_ID_MISMATCH")
        if "sha256" in response and response["sha256"] != digest:
            raise ValueError("FEEDBACK_ACK_HASH_MISMATCH")
        return {"status": "ACCEPTED" if response["status"] == "RECEIVED"
                else "DUPLICATE", "package_id": package_id}


def upload(url: str, token: str, envelope: bytes, *, timeout: int = 15) -> dict:
    """既存テスト・中央API用の互換入口。"""
    return FutureFeedbackApiTransport(url, timeout).send({"envelope": envelope}, token)


def transport_for(client: dict) -> FeedbackTransport:
    if client.get("transport") == "shared_php":
        return SharedServerTransport(client["endpoint"], client["client_id"])
    if client.get("transport", "api") == "api":
        return FutureFeedbackApiTransport(client["endpoint"])
    raise ValueError("FEEDBACK_TRANSPORT_INVALID")


def classify_connection_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:
            return "AUTH"
        if exc.code == 403:
            return "PRIVACY_POLICY"
        if exc.code == 404:
            return "CLIENT_ID"
        return "SERVER" if exc.code >= 500 else "SERVER_REJECTED"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return "NETWORK"
    if isinstance(exc, ValueError):
        code = str(exc)
        if code == "AUTH_FAILED":
            return "AUTH"
        if code == "CLIENT_NOT_ALLOWED":
            return "CLIENT_ID"
        if code in {"KEY_INVALID", "KEY_NOT_FOUND", "FEEDBACK_PUBLIC_KEY_INVALID"}:
            return "KEY"
        if code == "PRIVACY_REJECTED":
            return "PRIVACY_POLICY"
        return "SERVER"
    return "SERVER"


def send_pending(store: FeedbackStore, *, url: str, token: str,
                 sender=upload, transport: FeedbackTransport | None = None,
                 force: bool = False) -> dict:
    store.recover_uploading()
    result = {"sent": 0, "retryable": 0, "rejected": 0, "deferred": 0}
    for item in store.pending(force=force):
        package_id = item["package_id"]
        selected_kind = getattr(transport, "kind", "api")
        if (item.get("destination_url") not in {None, url}
                or (item.get("transport_kind") or "api") != selected_kind):
            store.mark(package_id, "REJECTED", "DESTINATION_CHANGED")
            result["rejected"] += 1
            continue
        if hashlib.sha256(item["envelope"]).hexdigest() != item["sha256"]:
            store.mark(package_id, "REJECTED", "LOCAL_HASH_MISMATCH")
            result["rejected"] += 1
            continue
        store.mark(package_id, "UPLOADING")
        try:
            response = (transport.send(item, token) if transport is not None else
                        sender(url, token, item["envelope"]))
            if response.get("package_id") != package_id or response.get("status") not in {
                "ACCEPTED", "DUPLICATE",
            }:
                raise ValueError("FEEDBACK_ACK_INVALID")
        except urllib.error.HTTPError as exc:
            retry = exc.code == 429 or exc.code >= 500
            store.mark(package_id, "FAILED_RETRYABLE" if retry else "REJECTED",
                       f"HTTP_{exc.code}")
            result["retryable" if retry else "rejected"] += 1
        except ValueError as exc:
            permanent = str(exc) in {
                "FEEDBACK_TLS_ENDPOINT_REQUIRED", "FEEDBACK_CREDENTIAL_REQUIRED",
                "FEEDBACK_CLIENT_INVALID", "FEEDBACK_PRIVACY_HEADER_INVALID",
                "FEEDBACK_LOCAL_HASH_MISMATCH", "FEEDBACK_REQUEST_ID_INVALID",
                "AUTH_FAILED", "CLIENT_NOT_ALLOWED", "KEY_INVALID", "KEY_NOT_FOUND",
                "PRIVACY_REJECTED",
            }
            store.mark(package_id, "REJECTED" if permanent else "FAILED_RETRYABLE",
                       (str(exc) if str(exc) in {"AUTH_FAILED", "CLIENT_NOT_ALLOWED",
                                                "KEY_INVALID", "KEY_NOT_FOUND",
                                                "PRIVACY_REJECTED"}
                        else "LOCAL_CONFIGURATION_INVALID") if permanent
                       else "NETWORK_OR_ACK_ERROR")
            result["rejected" if permanent else "retryable"] += 1
        except (OSError, TimeoutError):
            store.mark(package_id, "FAILED_RETRYABLE", "NETWORK_OR_ACK_ERROR")
            result["retryable"] += 1
        else:
            store.mark(package_id, "SENT")
            result["sent"] += 1
    result["deferred"] = store.unsent_count()
    return result
