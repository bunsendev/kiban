"""管理画面向けOIDC Authorization Code + PKCE交換。"""

import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


def _https_url(value: str, label: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError(f"{label}はuserinfo・fragmentのないHTTPS URLです")


@dataclass(frozen=True)
class OidcLoginSettings:
    authorization_url: str
    token_url: str
    client_id: str
    scopes: tuple[str, ...] = ("openid", "profile")
    redirect_path: str = "/ui/auth/callback"

    def __post_init__(self) -> None:
        _https_url(self.authorization_url, "OIDC authorization URL")
        _https_url(self.token_url, "OIDC token URL")
        if not self.client_id.strip() or len(self.client_id) > 500:
            raise ValueError("OIDC client IDが不正です")
        if (
            not self.scopes
            or "openid" not in self.scopes
            or len(set(self.scopes)) != len(self.scopes)
        ):
            raise ValueError("OIDC scopeには重複のないopenidが必要です")
        if any(
            not scope or len(scope) > 100 or any(char.isspace() for char in scope)
            for scope in self.scopes
        ):
            raise ValueError("OIDC scopeが不正です")
        if self.redirect_path != "/ui/auth/callback":
            raise ValueError("OIDC redirect pathは固定です")


class CodeExchange(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    code_verifier: str = Field(min_length=43, max_length=128)
    redirect_uri: str = Field(min_length=1, max_length=2048)


def exchange_code(settings: OidcLoginSettings, payload: CodeExchange) -> dict:
    if not _VERIFIER.fullmatch(payload.code_verifier):
        raise ValueError("PKCE code verifierが不正です")
    body = urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": settings.client_id,
            "code": payload.code,
            "code_verifier": payload.code_verifier,
            "redirect_uri": payload.redirect_uri,
        }
    ).encode("ascii")
    request = UrlRequest(
        settings.token_url,
        data=body,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            raw = response.read(65_537)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("OIDC code交換に失敗しました") from exc
    if len(raw) > 65_536:
        raise RuntimeError("OIDC token responseが大きすぎます")
    try:
        value = json.loads(raw)
        token = value["access_token"]
        token_type = value.get("token_type", "Bearer")
        expires_in = value.get("expires_in")
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("OIDC token responseが不正です") from exc
    if (
        not isinstance(token, str)
        or not token
        or len(token) > 16_384
        or token_type.lower() != "bearer"
    ):
        raise RuntimeError("OIDC token responseが不正です")
    if expires_in is not None and (
        not isinstance(expires_in, int) or not 1 <= expires_in <= 86_400
    ):
        raise RuntimeError("OIDC token有効期間が不正です")
    return {"access_token": token, "token_type": "Bearer", "expires_in": expires_in}


def install_oidc_login_routes(app, settings: OidcLoginSettings | None) -> None:
    router = APIRouter(prefix="/api/ui-auth", tags=["ui-auth"])

    @router.get("/config")
    def config():
        if settings is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "authorization_url": settings.authorization_url,
            "client_id": settings.client_id,
            "scopes": list(settings.scopes),
            "redirect_path": settings.redirect_path,
        }

    @router.post("/exchange")
    def exchange(payload: CodeExchange, request: Request):
        if settings is None:
            raise HTTPException(status_code=404, detail="OIDC UI loginは無効です")
        expected = str(request.base_url).rstrip("/") + settings.redirect_path
        if payload.redirect_uri != expected:
            raise HTTPException(status_code=400, detail="OIDC redirect URIが一致しません")
        try:
            return exchange_code(settings, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    app.include_router(router)
