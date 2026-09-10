"""Bearer credential、role別認可、HTTP security境界。"""

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware


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


_BEARER = HTTPBearer(auto_error=False)


class Authorizer:
    def __init__(self, authenticator: TokenAuthenticator) -> None:
        self.authenticator = authenticator

    def __call__(
        self,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
    ) -> Principal:
        principal = (
            None
            if credentials is None or credentials.scheme.lower() != "bearer"
            else self.authenticator.authenticate(credentials.credentials)
        )
        if principal is None:
            raise HTTPException(
                status_code=401,
                detail="認証が必要です",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return principal

    def require(self, permission: Permission):
        def dependency(principal: Annotated[Principal, Depends(self)]) -> Principal:
            if permission not in principal.permissions:
                raise HTTPException(status_code=403, detail="この操作の権限がありません")
            return principal

        return dependency


@dataclass(frozen=True)
class SecuritySettings:
    deployment_mode: str = "development"
    allowed_hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.deployment_mode not in {"development", "production"}:
            raise ValueError("deployment modeはdevelopmentまたはproductionです")
        if self.deployment_mode == "production" and not self.allowed_hosts:
            raise ValueError("productionではallowed hostsが必要です")
        if self.deployment_mode == "production" and "*" in self.allowed_hosts:
            raise ValueError("productionのallowed hostsに*は指定できません")

    @property
    def production(self) -> bool:
        return self.deployment_mode == "production"


def audit_payload(request: BaseModel, principal: Principal, actor_field: str) -> dict:
    payload = request.model_dump(mode="json")
    payload[actor_field] = principal.subject
    return payload


def _apply_security_headers(
    response: Response,
    request_id: str,
    *,
    api_response: bool,
    production_https: bool,
) -> Response:
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if api_response:
        response.headers["Cache-Control"] = "no-store"
    if production_https:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


def install_security_boundary(app: FastAPI, settings: SecuritySettings) -> None:
    if settings.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware("http")
    async def security_boundary(request: Request, call_next):
        request_id = str(uuid.uuid4())
        protected = request.url.path in {"/api", "/ui"} or request.url.path.startswith(
            ("/api/", "/ui/")
        )
        if settings.production and protected and request.url.scheme != "https":
            return _apply_security_headers(
                JSONResponse(
                    status_code=426,
                    content={
                        "detail": "production APIと管理画面はHTTPSが必要です",
                        "request_id": request_id,
                    },
                ),
                request_id,
                api_response=protected,
                production_https=False,
            )
        response = await call_next(request)
        return _apply_security_headers(
            response,
            request_id,
            api_response=request.url.path.startswith("/api"),
            production_https=settings.production and request.url.scheme == "https",
        )
