"""Phase 1Qのcredential、role別認可、監査主体、HTTPS境界。"""

import json

import pytest
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.api.factory import load_api_security
from forecast_provider.api.security import SecuritySettings, TokenAuthenticator
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.master import SqliteMasterStore

TOKENS = {
    "viewer": "viewer-token-00000000000000000000",
    "analyst": "analyst-token-0000000000000000000",
    "approver": "approver-token-000000000000000000",
    "admin": "admin-token-000000000000000000000",
}


def credential_json() -> str:
    return json.dumps(
        [
            {
                "token": TOKENS[name],
                "subject": f"{name}@example.test",
                "roles": [name.upper()],
            }
            for name in TOKENS
        ]
    )


def authorized(api: TestClient, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[role]}"}


def test_roles_are_enforced_and_audit_actor_comes_from_credential(tmp_path):
    database = tmp_path / "security.sqlite3"
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            TokenAuthenticator.from_json(credential_json()),
            master=SqliteMasterStore(database),
        )
    )

    viewer = api.get("/api/session", headers=authorized(api, "viewer"))
    assert viewer.json() == {
        "subject": "viewer@example.test",
        "roles": ["VIEWER"],
        "permissions": ["EXPORT", "READ"],
    }
    assert api.get("/api/runs/missing", headers=authorized(api, "viewer")).status_code == 404
    assert (
        api.post(
            "/api/runs",
            json={"experiment_id": "missing"},
            headers=authorized(api, "viewer"),
        ).status_code
        == 403
    )

    assert (
        api.post(
            "/api/runs",
            json={"experiment_id": "missing"},
            headers=authorized(api, "analyst"),
        ).status_code
        == 404
    )
    assert (
        api.post(
            "/api/products",
            json={"display_name": "拒否対象", "reason": "権限試験"},
            headers=authorized(api, "analyst"),
        ).status_code
        == 403
    )

    product = api.post(
        "/api/products",
        json={
            "display_name": "監査主体試験",
            "created_by": "spoofed@example.test",
            "reason": "credential由来の主体を確認",
        },
        headers=authorized(api, "approver"),
    )
    assert product.status_code == 201
    products = api.get("/api/products", headers=authorized(api, "viewer")).json()
    assert products[0]["created_by"] == "approver@example.test"
    assert (
        api.post(
            "/api/runs",
            json={"experiment_id": "missing"},
            headers=authorized(api, "approver"),
        ).status_code
        == 403
    )
    assert (
        api.post(
            "/api/runs",
            json={"experiment_id": "missing"},
            headers=authorized(api, "admin"),
        ).status_code
        == 404
    )
    unauthenticated = api.get("/api/session")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == "Bearer"


def test_production_requires_https_trusted_host_and_security_headers(tmp_path):
    database = tmp_path / "production-security.sqlite3"
    app = create_app(
        SqliteRunStore(database),
        SqliteCatalogStore(database),
        TokenAuthenticator.from_json(credential_json()),
        security_settings=SecuritySettings("production", ("kibanserver",)),
    )

    with TestClient(app, base_url="http://kibanserver") as plain:
        assert plain.get("/health").status_code == 200
        rejected = plain.get("/ui")
        assert rejected.status_code == 426
        assert rejected.json()["request_id"] == rejected.headers["x-request-id"]
        assert rejected.headers["permissions-policy"] == (
            "camera=(), microphone=(), geolocation=()"
        )

    with TestClient(app, base_url="https://kibanserver") as secure:
        page = secure.get("/ui")
        session = secure.get("/api/session", headers=authorized(secure, "admin"))
        assert page.status_code == session.status_code == 200
        assert secure.get("/openapi.json").status_code == 404
        assert session.headers["cache-control"] == "no-store"
        assert session.headers["strict-transport-security"] == "max-age=31536000"
        assert session.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
        assert session.headers["x-frame-options"] == "DENY"

    with TestClient(app, base_url="https://untrusted.example") as untrusted:
        assert untrusted.get("/ui").status_code == 400


def test_environment_security_configuration_rejects_unsafe_production():
    development, settings = load_api_security(
        {"KIBAN_API_TOKEN": "local", "KIBAN_API_SUBJECT": "developer@example.test"}
    )
    assert development.authenticate("local").subject == "developer@example.test"
    assert settings.production is False

    with pytest.raises(RuntimeError, match="productionではKIBAN_API_CREDENTIALS"):
        load_api_security(
            {
                "KIBAN_API_TOKEN": "shared",
                "KIBAN_DEPLOYMENT_MODE": "production",
                "KIBAN_ALLOWED_HOSTS": "kiban.example.test",
            }
        )
    with pytest.raises(RuntimeError, match="32文字以上"):
        load_api_security(
            {
                "KIBAN_API_CREDENTIALS": json.dumps(
                    [{"token": "short", "subject": "x", "roles": ["ADMIN"]}]
                ),
                "KIBAN_DEPLOYMENT_MODE": "production",
                "KIBAN_ALLOWED_HOSTS": "kiban.example.test",
            }
        )
    with pytest.raises(RuntimeError, match="allowed hosts"):
        load_api_security(
            {
                "KIBAN_API_CREDENTIALS": credential_json(),
                "KIBAN_DEPLOYMENT_MODE": "production",
            }
        )
    production, settings = load_api_security(
        {
            "KIBAN_API_CREDENTIALS": credential_json(),
            "KIBAN_DEPLOYMENT_MODE": "production",
            "KIBAN_ALLOWED_HOSTS": "kiban.example.test,localhost",
        }
    )
    assert production.authenticate(TOKENS["viewer"]).subject == "viewer@example.test"
    assert settings.allowed_hosts == ("kiban.example.test", "localhost")
    assert TOKENS["viewer"] not in repr(vars(production))
