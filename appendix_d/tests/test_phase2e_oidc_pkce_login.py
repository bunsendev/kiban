"""Phase 2E 管理画面OIDC Authorization Code + PKCE。"""

from fastapi.testclient import TestClient

from forecast_provider.api import oidc_login
from forecast_provider.api.app import create_app
from forecast_provider.api.factory import load_oidc_login_settings
from forecast_provider.api.oidc_login import OidcLoginSettings
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore


def _settings() -> OidcLoginSettings:
    return OidcLoginSettings(
        "https://id.example.test/authorize",
        "https://id.example.test/token",
        "kiban-ui",
        ("openid", "profile"),
    )


def test_ui_exposes_public_config_and_exchanges_code_without_refresh_token(tmp_path, monkeypatch):
    app = create_app(
        SqliteRunStore(tmp_path / "pkce.sqlite3"),
        SqliteCatalogStore(tmp_path / "pkce.sqlite3"),
        "manual-token",
        oidc_login_settings=_settings(),
    )
    seen = {}

    def exchange(_settings, payload):
        seen["payload"] = payload
        return {"access_token": "signed-access-token", "token_type": "Bearer", "expires_in": 300}

    monkeypatch.setattr(oidc_login, "exchange_code", exchange)
    client = TestClient(app)
    config = client.get("/api/ui-auth/config")
    assert config.json() == {
        "enabled": True,
        "authorization_url": "https://id.example.test/authorize",
        "client_id": "kiban-ui",
        "scopes": ["openid", "profile"],
        "redirect_path": "/ui/auth/callback",
    }
    response = client.post(
        "/api/ui-auth/exchange",
        json={
            "code": "one-time-code",
            "code_verifier": "a" * 43,
            "redirect_uri": "http://testserver/ui/auth/callback",
        },
    )
    assert response.json() == {
        "access_token": "signed-access-token",
        "token_type": "Bearer",
        "expires_in": 300,
    }
    assert seen["payload"].code == "one-time-code"
    assert client.get("/ui/auth/callback").status_code == 200
    script = client.get("/ui/assets/pkce.js").text
    assert 'url.searchParams.set("code_challenge_method", "S256")' in script
    assert "crypto.subtle.digest" in script
    assert "history.replaceState" in script
    assert "localStorage" not in script
    assert 'setItem(STORAGE_KEY, JSON.stringify({ verifier, state, returnPath' in script
    assert "sessionStorage.setItem(STORAGE_KEY, token" not in script


def test_exchange_rejects_redirect_mismatch_and_disabled_mode(tmp_path):
    database = tmp_path / "disabled.sqlite3"
    disabled = TestClient(
        create_app(SqliteRunStore(database), SqliteCatalogStore(database), "token")
    )
    assert disabled.get("/api/ui-auth/config").json() == {"enabled": False}
    assert (
        disabled.post(
            "/api/ui-auth/exchange",
            json={
                "code": "code",
                "code_verifier": "a" * 43,
                "redirect_uri": "http://testserver/ui/auth/callback",
            },
        ).status_code
        == 404
    )

    enabled = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            oidc_login_settings=_settings(),
        )
    )
    assert (
        enabled.post(
            "/api/ui-auth/exchange",
            json={
                "code": "code",
                "code_verifier": "a" * 43,
                "redirect_uri": "https://attacker.example/callback",
            },
        ).status_code
        == 400
    )


def test_factory_loads_complete_public_client_settings_and_rejects_partial():
    settings = load_oidc_login_settings(
        {
            "KIBAN_OIDC_AUTHORIZATION_URL": "https://id.example.test/authorize",
            "KIBAN_OIDC_TOKEN_URL": "https://id.example.test/token",
            "KIBAN_OIDC_CLIENT_ID": "kiban-ui",
            "KIBAN_OIDC_SCOPES": "openid profile email",
        }
    )
    assert settings is not None
    assert settings.scopes == ("openid", "profile", "email")

    import pytest

    with pytest.raises(RuntimeError, match="不足"):
        load_oidc_login_settings({"KIBAN_OIDC_CLIENT_ID": "partial"})


def test_factory_requires_complete_https_pkce_settings():
    assert load_oidc_login_settings({}) is None
    settings = load_oidc_login_settings(
        {
            "KIBAN_OIDC_AUTHORIZATION_URL": "https://id.example.test/authorize",
            "KIBAN_OIDC_TOKEN_URL": "https://id.example.test/token",
            "KIBAN_OIDC_CLIENT_ID": "kiban-ui",
            "KIBAN_OIDC_SCOPES": "openid profile email",
        }
    )
    assert settings and settings.scopes == ("openid", "profile", "email")
