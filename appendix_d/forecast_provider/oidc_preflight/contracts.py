"""OIDC接続プリフライトの入力契約。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..oidc_algorithms import ASYMMETRIC_ALGORITHMS

FORMAT_VERSION = "kiban-oidc-preflight-report/v1"
SUITE_ID = "kiban-oidc-preflight/v1"
USER_AGENT = "Yosoku-Kiban-OIDC-Preflight/2.9"


def require_https_url(value: str, label: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError(f"{label}はuserinfo・fragmentのないHTTPS URLです")
    return value


def url_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OidcPreflightSettings:
    issuer: str
    authorization_url: str
    token_url: str
    jwks_url: str
    algorithms: tuple[str, ...] = ("RS256",)
    timeout_seconds: float = 5.0
    max_response_bytes: int = 131_072

    def __post_init__(self) -> None:
        for value, label in (
            (self.issuer, "OIDC issuer"),
            (self.authorization_url, "OIDC authorization URL"),
            (self.token_url, "OIDC token URL"),
            (self.jwks_url, "OIDC JWKS URL"),
        ):
            require_https_url(value, label)
        if urlsplit(self.issuer).query:
            raise ValueError("OIDC issuerにqueryは指定できません")
        if not self.algorithms or not set(self.algorithms) <= ASYMMETRIC_ALGORITHMS:
            raise ValueError("OIDC algorithmは許可された非対称署名方式を指定します")
        if len(set(self.algorithms)) != len(self.algorithms):
            raise ValueError("OIDC algorithmは重複できません")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("timeoutは0.1秒以上30秒以下です")
        if not 1_024 <= self.max_response_bytes <= 1_048_576:
            raise ValueError("最大応答サイズは1 KiB以上1 MiB以下です")

    @property
    def discovery_url(self) -> str:
        return self.issuer.rstrip("/") + "/.well-known/openid-configuration"

    def public_conditions(self) -> dict:
        return {
            "suite_id": SUITE_ID,
            "issuer_sha256": url_fingerprint(self.issuer),
            "authorization_url_sha256": url_fingerprint(self.authorization_url),
            "token_url_sha256": url_fingerprint(self.token_url),
            "jwks_url_sha256": url_fingerprint(self.jwks_url),
            "algorithms": list(self.algorithms),
            "timeout_seconds": self.timeout_seconds,
            "max_response_bytes": self.max_response_bytes,
            "redirects_allowed": False,
            "tls_verification": "SYSTEM_TRUST_STORE_AND_HOSTNAME",
        }
