"""比較・受入・採用管理画面の配信境界。"""

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore


def test_management_ui_serves_modular_assets_without_persisting_token(tmp_path):
    database = tmp_path / "ui.sqlite3"
    api = TestClient(
        create_app(SqliteRunStore(database), SqliteCatalogStore(database), "token")
    )

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
    assert "localStorage" not in script.text + api_client.text
    assert "sessionStorage" not in script.text + api_client.text
    assert api.get("/api/runs/missing").status_code == 401
