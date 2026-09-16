"""認証主体、role認可、固定・更新可能なBearer credential。"""

import hashlib
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel


class Role(StrEnum):
    VIEWER = "VIEWER"
    ANALYST = "ANALYST"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"


class Permission(StrEnum):
    READ = "READ"
    ANALYZE = "ANALYZE"
    APPROVE = "APPROVE"
    EXPORT = "EXPORT"
    MANAGE_RESOURCE = "MANAGE_RESOURCE"


ROLE_PERMISSIONS = {
    Role.VIEWER: frozenset({Permission.READ, Permission.EXPORT}),
    Role.ANALYST: frozenset({Permission.READ, Permission.ANALYZE, Permission.EXPORT}),
    Role.APPROVER: frozenset({Permission.READ, Permission.APPROVE, Permission.EXPORT}),
    Role.ADMIN: frozenset(Permission),
}


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: tuple[Role, ...]

    @property
    def permissions(self) -> frozenset[Permission]:
        return frozenset(
            permission
            for role in self.roles
            for permission in ROLE_PERMISSIONS[role]
        )


class Authenticator(Protocol):
    @property
    def production_ready(self) -> bool: ...

    def authenticate(self, token: str) -> Principal | None: ...

    def readiness(self) -> bool: ...


@dataclass(frozen=True)
class _Credential:
    token_digest: bytes
    principal: Principal


class TokenAuthenticator:
    def __init__(
        self, credentials: list[_Credential], production_ready: bool = False
    ) -> None:
        if not credentials:
            raise ValueError("API credentialを1件以上設定してください")
        digests = [item.token_digest for item in credentials]
        if len(set(digests)) != len(digests):
            raise ValueError("API tokenは重複できません")
        self._credentials = tuple(credentials)
        self._production_ready = production_ready

    @property
    def production_ready(self) -> bool:
        return self._production_ready

    @classmethod
    def single(
        cls,
        token: str,
        subject: str = "local-admin",
        roles: tuple[Role, ...] = (Role.ADMIN,),
    ) -> "TokenAuthenticator":
        return cls([cls._make_credential(token, subject, roles)])

    @classmethod
    def from_json(cls, source: str) -> "TokenAuthenticator":
        try:
            values = json.loads(source)
        except json.JSONDecodeError as exc:
            raise ValueError("KIBAN_API_CREDENTIALSは正しいJSONで指定します") from exc
        if not isinstance(values, list):
            raise ValueError("KIBAN_API_CREDENTIALSはcredential配列です")
        if len(values) > 100:
            raise ValueError("API credentialは100件以下にしてください")
        credentials = []
        for value in values:
            if not isinstance(value, dict) or set(value) != {"token", "subject", "roles"}:
                raise ValueError("credentialはtoken、subject、rolesだけを指定します")
            raw_roles = value["roles"]
            if not isinstance(raw_roles, list) or not raw_roles:
                raise ValueError("credential rolesは1件以上の配列です")
            try:
                roles = tuple(dict.fromkeys(Role(role) for role in raw_roles))
            except (TypeError, ValueError) as exc:
                raise ValueError("未知のcredential roleです") from exc
            if not isinstance(value["token"], str) or len(value["token"]) < 32:
                raise ValueError("複数credentialのAPI tokenは32文字以上にしてください")
            credentials.append(cls._make_credential(value["token"], value["subject"], roles))
        return cls(credentials, production_ready=True)

    @staticmethod
    def _make_credential(
        token: object, subject: object, roles: tuple[Role, ...]
    ) -> _Credential:
        if not isinstance(token, str) or not token.strip() or token != token.strip():
            raise ValueError("API tokenは空にできません")
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("credential subjectは空にできません")
        normalized_subject = subject.strip()
        if len(normalized_subject) > 200 or any(
            ord(char) < 32 for char in normalized_subject
        ):
            raise ValueError("credential subjectに制御文字または201文字以上は使えません")
        if not roles:
            raise ValueError("credential roleを1件以上指定してください")
        return _Credential(
            hashlib.sha256(token.encode("utf-8")).digest(),
            Principal(normalized_subject, roles),
        )

    def authenticate(self, token: str) -> Principal | None:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        matched = None
        for credential in self._credentials:
            if secrets.compare_digest(digest, credential.token_digest):
                matched = credential.principal
        return matched

    def readiness(self) -> bool:
        return True


class ReloadingTokenAuthenticator:
    """Atomic置換されるcredential JSONを定期再読込する。"""

    def __init__(
        self,
        path: Path,
        refresh_interval_seconds: float = 5.0,
        max_bytes: int = 65_536,
    ) -> None:
        if refresh_interval_seconds < 0:
            raise ValueError("credential refresh intervalは0以上です")
        self.path = path.resolve()
        self.refresh_interval_seconds = refresh_interval_seconds
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._authenticator: TokenAuthenticator | None = None
        self._content_digest: bytes | None = None
        self._last_check = 0.0
        self._healthy = False
        self._logger = logging.getLogger("kiban.auth")
        self._reload(force=True, raise_on_error=True)

    @property
    def production_ready(self) -> bool:
        return True

    def _read(self) -> bytes:
        if not self.path.is_file():
            raise ValueError("credential fileが存在しません")
        size = self.path.stat().st_size
        if size <= 0 or size > self.max_bytes:
            raise ValueError("credential fileは1 byte以上64 KiB以下です")
        return self.path.read_bytes()

    def _reload(self, *, force: bool, raise_on_error: bool = False) -> None:
        with self._lock:
            current = time.monotonic()
            if not force and current - self._last_check < self.refresh_interval_seconds:
                return
            self._last_check = current
            try:
                content = self._read()
                content_digest = hashlib.sha256(content).digest()
                if self._healthy and secrets.compare_digest(
                    content_digest, self._content_digest or b""
                ):
                    return
                authenticator = TokenAuthenticator.from_json(content.decode("utf-8"))
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                self._healthy = False
                self._logger.error(
                    "credential_file_reload_failed path=%s error_type=%s",
                    self.path,
                    type(exc).__name__,
                )
                if raise_on_error:
                    raise ValueError("credential fileを読込めません") from exc
                return
            self._authenticator = authenticator
            self._content_digest = content_digest
            self._healthy = True

    def authenticate(self, token: str) -> Principal | None:
        self._reload(force=False)
        with self._lock:
            if not self._healthy or self._authenticator is None:
                return None
            return self._authenticator.authenticate(token)

    def readiness(self) -> bool:
        self._reload(force=True)
        with self._lock:
            return self._healthy


_BEARER = HTTPBearer(auto_error=False)


class Authorizer:
    def __init__(self, authenticator: Authenticator) -> None:
        self.authenticator = authenticator

    def __call__(
        self,
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
    ) -> Principal:
        principal = (
            None
            if credentials is None
            or credentials.scheme.lower() != "bearer"
            or len(credentials.credentials) > 16_384
            else self.authenticator.authenticate(credentials.credentials)
        )
        if principal is None:
            raise HTTPException(
                status_code=401,
                detail="認証が必要です",
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.principal = principal
        return principal

    def require(self, permission: Permission):
        def dependency(principal: Annotated[Principal, Depends(self)]) -> Principal:
            if permission not in principal.permissions:
                raise HTTPException(status_code=403, detail="この操作の権限がありません")
            return principal

        return dependency


def audit_payload(request: BaseModel, principal: Principal, actor_field: str) -> dict:
    payload = request.model_dump(mode="json")
    payload[actor_field] = principal.subject
    return payload
