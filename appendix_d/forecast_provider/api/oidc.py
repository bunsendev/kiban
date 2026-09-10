"""外部IdPが発行するJWT access tokenの検証。"""

import logging
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import jwt

from .authentication import Principal, Role

_ASYMMETRIC_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"}
)
_CLAIM_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


class JwksClient(Protocol):
    def get_signing_key_from_jwt(self, token: str): ...

    def get_jwk_set(self, refresh: bool = False): ...


@dataclass(frozen=True)
class OidcSettings:
    issuer: str
    audience: str
    jwks_url: str
    role_claim: str = "roles"
    role_mapping: tuple[tuple[str, Role], ...] = ()
    algorithms: tuple[str, ...] = ("RS256",)
    leeway_seconds: int = 60

    def __post_init__(self) -> None:
        _require_https_url(self.issuer, "OIDC issuer")
        _require_https_url(self.jwks_url, "OIDC JWKS URL")
        if not self.audience.strip() or len(self.audience) > 500:
            raise ValueError("OIDC audienceは1文字以上500文字以下です")
        if not _CLAIM_NAME.fullmatch(self.role_claim):
            raise ValueError("OIDC role claimが不正です")
        if not self.algorithms or not set(self.algorithms) <= _ASYMMETRIC_ALGORITHMS:
            raise ValueError("OIDC algorithmは許可された非対称署名方式を指定します")
        if len(set(self.algorithms)) != len(self.algorithms):
            raise ValueError("OIDC algorithmは重複できません")
        if not 0 <= self.leeway_seconds <= 300:
            raise ValueError("OIDC leewayは0秒以上300秒以下です")
        external_roles = [external for external, _role in self.role_mapping]
        if len(set(external_roles)) != len(external_roles):
            raise ValueError("OIDC role mappingの外部roleは重複できません")
        if any(not value or len(value) > 200 for value in external_roles):
            raise ValueError("OIDC role mappingの外部roleが不正です")


def _require_https_url(value: str, label: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError(f"{label}はuserinfo・fragmentのないHTTPS URLです")


def _claim(claims: dict, dotted_name: str):
    value = claims
    for part in dotted_name.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _subject(claims: dict) -> str | None:
    subject = claims.get("sub")
    if not isinstance(subject, str):
        return None
    subject = subject.strip()
    if (
        not subject
        or len(subject) > 200
        or any(ord(character) < 32 for character in subject)
    ):
        return None
    return subject


def _roles(value, mapping: tuple[tuple[str, Role], ...]) -> tuple[Role, ...]:
    if isinstance(value, str):
        raw_roles = [value]
    elif isinstance(value, (list, tuple)) and all(
        isinstance(item, str) for item in value
    ):
        raw_roles = value
    else:
        return ()
    if mapping:
        lookup = dict(mapping)
        roles = [lookup[item] for item in raw_roles if item in lookup]
    else:
        try:
            roles = [Role(item) for item in raw_roles]
        except ValueError:
            return ()
    return tuple(dict.fromkeys(roles))


class OidcAuthenticator:
    def __init__(self, settings: OidcSettings, jwks_client: JwksClient | None = None) -> None:
        self.settings = settings
        self._jwks = jwks_client or jwt.PyJWKClient(
            settings.jwks_url,
            cache_keys=True,
            max_cached_keys=16,
            cache_jwk_set=True,
            lifespan=300,
            headers={"User-Agent": "Yosoku-Kiban/2.9"},
            timeout=5,
        )
        self._logger = logging.getLogger("kiban.auth")

    @property
    def production_ready(self) -> bool:
        return True

    def authenticate(self, token: str) -> Principal | None:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self.settings.algorithms),
                audience=self.settings.audience,
                issuer=self.settings.issuer,
                leeway=self.settings.leeway_seconds,
                options={"require": ["sub", "iat", "exp"]},
            )
            subject = _subject(claims)
            roles = _roles(_claim(claims, self.settings.role_claim), self.settings.role_mapping)
            if subject is None or not roles:
                return None
            return Principal(subject, roles)
        except (jwt.PyJWTError, jwt.PyJWKClientError, AttributeError, TypeError, ValueError) as exc:
            self._logger.warning("oidc_authentication_failed error_type=%s", type(exc).__name__)
            return None

    def readiness(self) -> bool:
        try:
            key_set = self._jwks.get_jwk_set()
            return bool(key_set.keys)
        except (jwt.PyJWTError, jwt.PyJWKClientError, AttributeError, OSError):
            return False
