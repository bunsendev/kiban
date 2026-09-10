"""Phase 1RのOIDCとcredential rotation。"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.api.authentication import ReloadingTokenAuthenticator, Role
from forecast_provider.api.factory import load_api_security, load_secret_setting
from forecast_provider.api.oidc import OidcAuthenticator, OidcSettings
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore


def credentials(token: str, subject: str, role: str = "VIEWER") -> str:
    return json.dumps([{"token": token, "subject": subject, "roles": [role]}])


class FakeJwksClient:
    def __init__(self, keys: dict[str, object]) -> None:
        self.keys = keys

    def get_signing_key_from_jwt(self, token: str):
        key_id = jwt.get_unverified_header(token)["kid"]
        return SimpleNamespace(key=self.keys[key_id])

    def get_jwk_set(self, refresh: bool = False):
        return SimpleNamespace(keys=list(self.keys.values()))


def signed_token(private_key, **overrides) -> str:
    current = datetime.now(UTC)
    claims = {
        "iss": "https://id.example.test/tenant",
        "aud": "kiban-api",
        "sub": "analyst@example.test",
        "iat": current,
        "exp": current + timedelta(minutes=5),
        "realm_access": {"roles": ["forecast-analyst", "unrelated"]},
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "key-1"})


def test_oidc_validates_signature_claims_and_role_mapping():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = FakeJwksClient({"key-1": private_key.public_key()})
    authenticator = OidcAuthenticator(
        OidcSettings(
            issuer="https://id.example.test/tenant",
            audience="kiban-api",
            jwks_url="https://id.example.test/tenant/keys",
            role_claim="realm_access.roles",
            role_mapping=(("forecast-analyst", Role.ANALYST),),
            leeway_seconds=0,
        ),
        client,
    )

    principal = authenticator.authenticate(signed_token(private_key))
    assert principal is not None
    assert principal.subject == "analyst@example.test"
    assert principal.roles == (Role.ANALYST,)
    assert authenticator.readiness() is True
    assert authenticator.authenticate(signed_token(other_key)) is None
    assert authenticator.authenticate(signed_token(private_key, aud="other-api")) is None
    assert authenticator.authenticate(
        signed_token(private_key, iss="https://other.example.test")
    ) is None
    assert authenticator.authenticate(
        signed_token(private_key, exp=datetime.now(UTC) - timedelta(minutes=1))
    ) is None
    assert authenticator.authenticate(
        signed_token(private_key, realm_access={"roles": ["unmapped"]})
    ) is None


def test_oidc_principal_is_used_by_fastapi_session(tmp_path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authenticator = OidcAuthenticator(
        OidcSettings(
            issuer="https://id.example.test/tenant",
            audience="kiban-api",
            jwks_url="https://id.example.test/tenant/keys",
            role_claim="realm_access.roles",
            role_mapping=(("forecast-analyst", Role.ANALYST),),
        ),
        FakeJwksClient({"key-1": private_key.public_key()}),
    )
    database = tmp_path / "oidc-api.sqlite3"
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            authenticator,
        )
    )
    response = api.get(
        "/api/session",
        headers={"Authorization": f"Bearer {signed_token(private_key)}"},
    )
    assert response.status_code == 200
    assert response.json()["subject"] == "analyst@example.test"
    assert response.json()["roles"] == ["ANALYST"]


def test_oidc_settings_reject_symmetric_algorithm_and_plain_http():
    with pytest.raises(ValueError, match="HTTPS URL"):
        OidcSettings("http://id.example.test", "api", "https://id.example.test/keys")
    with pytest.raises(ValueError, match="非対称署名"):
        OidcSettings(
            "https://id.example.test",
            "api",
            "https://id.example.test/keys",
            algorithms=("HS256",),
        )


def test_credential_file_rotates_and_fails_closed(tmp_path: Path):
    old_token = "old-token-00000000000000000000000"
    new_token = "new-token-00000000000000000000000"
    path = tmp_path / "credentials.json"
    path.write_text(credentials(old_token, "old@example.test"), encoding="utf-8")
    authenticator = ReloadingTokenAuthenticator(path, refresh_interval_seconds=0)

    assert authenticator.authenticate(old_token).subject == "old@example.test"
    replacement = tmp_path / "replacement.json"
    replacement.write_text(credentials(new_token, "new@example.test"), encoding="utf-8")
    replacement.replace(path)
    assert authenticator.authenticate(old_token) is None
    assert authenticator.authenticate(new_token).subject == "new@example.test"

    path.write_text("not-json", encoding="utf-8")
    assert authenticator.readiness() is False
    assert authenticator.authenticate(new_token) is None
    path.write_text(credentials(new_token, "restored@example.test"), encoding="utf-8")
    assert authenticator.readiness() is True
    assert authenticator.authenticate(new_token).subject == "restored@example.test"


def test_factory_selects_oidc_and_reads_secret_file(tmp_path: Path):
    dsn_file = tmp_path / "postgres-dsn"
    dsn_file.write_text("postgresql://user:password@db/kiban\n", encoding="utf-8")
    assert load_secret_setting(
        {"KIBAN_POSTGRES_DSN_FILE": str(dsn_file)}, "KIBAN_POSTGRES_DSN"
    ) == "postgresql://user:password@db/kiban"
    with pytest.raises(RuntimeError, match="同時に設定"):
        load_secret_setting(
            {
                "KIBAN_POSTGRES_DSN": "direct",
                "KIBAN_POSTGRES_DSN_FILE": str(dsn_file),
            },
            "KIBAN_POSTGRES_DSN",
        )

    authenticator, settings = load_api_security(
        {
            "KIBAN_AUTH_MODE": "oidc",
            "KIBAN_DEPLOYMENT_MODE": "production",
            "KIBAN_ALLOWED_HOSTS": "kiban.example.test",
            "KIBAN_OIDC_ISSUER": "https://id.example.test/tenant",
            "KIBAN_OIDC_AUDIENCE": "kiban-api",
            "KIBAN_OIDC_JWKS_URL": "https://id.example.test/tenant/keys",
            "KIBAN_OIDC_ROLE_CLAIM": "roles",
            "KIBAN_OIDC_ROLE_MAPPING": '{"operator":"ADMIN"}',
        }
    )
    assert isinstance(authenticator, OidcAuthenticator)
    assert settings.production is True
    with pytest.raises(RuntimeError, match="同時に設定"):
        load_api_security(
            {
                "KIBAN_AUTH_MODE": "oidc",
                "KIBAN_API_TOKEN": "forbidden",
                "KIBAN_OIDC_ISSUER": "https://id.example.test",
                "KIBAN_OIDC_AUDIENCE": "kiban-api",
                "KIBAN_OIDC_JWKS_URL": "https://id.example.test/keys",
            }
        )

    credential_file = tmp_path / "api-credentials.json"
    credential_file.write_text(
        credentials("file-token-0000000000000000000000", "file@example.test"),
        encoding="utf-8",
    )
    rotating, settings = load_api_security(
        {
            "KIBAN_AUTH_MODE": "token",
            "KIBAN_DEPLOYMENT_MODE": "production",
            "KIBAN_ALLOWED_HOSTS": "kiban.example.test",
            "KIBAN_API_CREDENTIALS_FILE": str(credential_file),
            "KIBAN_CREDENTIAL_REFRESH_SECONDS": "0",
        }
    )
    assert isinstance(rotating, ReloadingTokenAuthenticator)
    assert rotating.readiness() is True
    assert settings.production is True
