"""比較・採用・Lifecycle管理画面の配信境界。"""

import re

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore


def test_management_ui_serves_modular_assets_without_persisting_token(tmp_path):
    database = tmp_path / "ui.sqlite3"
    api = TestClient(create_app(SqliteRunStore(database), SqliteCatalogStore(database), "token"))

    page = api.get("/ui")
    script = api.get("/ui/assets/app.js")
    api_client = api.get("/ui/assets/api.js")
    styles = api.get("/ui/assets/styles.css")

    assert page.status_code == script.status_code == api_client.status_code == 200
    assert styles.status_code == 200
    assert "予測採用ワークスペース" in page.text
    assert 'type="module" src="/ui/assets/app.js"' in page.text
    assert page.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert script.headers["x-content-type-options"] == "nosniff"
    assert script.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert "localStorage" not in script.text + api_client.text
    assert "sessionStorage" not in script.text + api_client.text
    assert "export-requested-by" not in page.text
    assert 'request("/api/session")' in api_client.text
    session = api.get("/api/session", headers={"Authorization": "Bearer token"})
    assert session.json()["subject"] == "local-admin"
    assert session.json()["roles"] == ["ADMIN"]
    assert api.get("/api/runs/missing").status_code == 401


def test_lifecycle_ui_serves_separate_modules_with_complete_dom_contract(tmp_path):
    database = tmp_path / "lifecycle-ui.sqlite3"
    api = TestClient(create_app(SqliteRunStore(database), SqliteCatalogStore(database), "token"))

    page = api.get("/ui/lifecycle")
    app = api.get("/ui/assets/lifecycle_app.js")
    client = api.get("/ui/assets/lifecycle_api.js")
    renderer = api.get("/ui/assets/lifecycle_render.js")
    styles = api.get("/ui/assets/lifecycle.css")

    assert all(value.status_code == 200 for value in (page, app, client, renderer, styles))
    assert "Lifecycle運用" in page.text
    assert 'type="module" src="/ui/assets/lifecycle_app.js"' in page.text
    assert 'href="/ui"' in page.text
    assert api.get("/ui").text.find('href="/ui/lifecycle"') >= 0
    assert page.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    scripts = app.text + client.text + renderer.text
    assert "localStorage" not in scripts
    assert "sessionStorage" not in scripts
    assert 'request("/api/lifecycle-plans")' in client.text
    assert 'data-permission="ANALYZE"' in page.text
    assert 'data-permission="APPROVE"' in page.text

    ids = set(re.findall(r'id="([^"]+)"', page.text))
    references = set(re.findall(r'(?:byId|document\.getElementById)\("([^"]+)"\)', scripts))
    assert references <= ids
