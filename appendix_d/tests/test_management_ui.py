"""比較・採用・Lifecycle管理画面の配信境界。"""

import re

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.ingestion import SqliteIngestionStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.mapping_dry_run import SqliteMappingDryRunJobStore
from forecast_provider.master import SqliteMasterStore
from forecast_provider.normalization import SqliteNormalizationStore
from forecast_provider.resource_cost import SqliteResourceCostStore


def test_management_ui_serves_modular_assets_without_persisting_token(tmp_path):
    database = tmp_path / "ui.sqlite3"
    api = TestClient(create_app(SqliteRunStore(database), SqliteCatalogStore(database), "token"))

    page = api.get("/ui")
    script = api.get("/ui/assets/app.js")
    api_client = api.get("/ui/assets/api.js")
    pkce = api.get("/ui/assets/pkce.js")
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
    assert "access_token" not in pkce.text.split("sessionStorage.setItem", 1)[1].split(";", 1)[0]
    assert "localStorage" not in pkce.text
    assert 'code_challenge_method", "S256"' in pkce.text
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


def test_readiness_ui_serves_separate_modules_with_complete_dom_contract(tmp_path):
    database = tmp_path / "readiness-ui.sqlite3"
    api = TestClient(create_app(SqliteRunStore(database), SqliteCatalogStore(database), "token"))

    page = api.get("/ui/readiness")
    app = api.get("/ui/assets/readiness_app.js")
    client = api.get("/ui/assets/readiness_api.js")
    renderer = api.get("/ui/assets/readiness_render.js")
    styles = api.get("/ui/assets/readiness.css")

    assert all(value.status_code == 200 for value in (page, app, client, renderer, styles))
    assert "取扱期間・欠測判定" in page.text
    assert 'type="module" src="/ui/assets/readiness_app.js"' in page.text
    assert 'href="/ui"' in page.text
    assert 'href="/ui/lifecycle"' in page.text
    assert 'href="/ui/readiness"' in api.get("/ui").text
    assert 'href="/ui/readiness"' in api.get("/ui/lifecycle").text
    assert page.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    scripts = app.text + client.text + renderer.text
    assert "localStorage" not in scripts
    assert "sessionStorage" not in scripts
    assert 'request("/api/daily-builds")' in client.text
    assert 'data-permission="APPROVE"' in page.text

    ids = set(re.findall(r'id="([^"]+)"', page.text))
    references = set(re.findall(r'(?:byId|document\.getElementById)\("([^"]+)"\)', scripts))
    assert references <= ids


def test_selection_ui_serves_separate_modules_with_complete_dom_contract(tmp_path):
    database = tmp_path / "selection-ui.sqlite3"
    api = TestClient(create_app(SqliteRunStore(database), SqliteCatalogStore(database), "token"))

    page = api.get("/ui/selection")
    app = api.get("/ui/assets/selection_app.js")
    client = api.get("/ui/assets/selection_api.js")
    renderer = api.get("/ui/assets/selection_render.js")
    styles = api.get("/ui/assets/selection.css")

    assert all(value.status_code == 200 for value in (page, app, client, renderer, styles))
    assert "重要品目候補・選定" in page.text
    assert 'type="module" src="/ui/assets/selection_app.js"' in page.text
    assert 'href="/ui/readiness"' in page.text
    assert 'href="/ui/selection"' in api.get("/ui").text
    assert 'href="/ui/selection"' in api.get("/ui/lifecycle").text
    assert 'href="/ui/selection"' in api.get("/ui/readiness").text
    assert page.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    scripts = app.text + client.text + renderer.text
    assert "localStorage" not in scripts
    assert "sessionStorage" not in scripts
    assert 'request("/api/selection-candidate-jobs")' in client.text
    assert 'request("/api/selections")' in client.text
    assert 'data-permission="ANALYZE"' in page.text
    assert 'data-permission="APPROVE"' in page.text

    ids = set(re.findall(r'id="([^"]+)"', page.text))
    assert len(ids) == len(re.findall(r'id="([^"]+)"', page.text))
    references = set(re.findall(r'(?:byId|document\.getElementById)\("([^"]+)"\)', scripts))
    assert references <= ids


def test_acceptance_ui_serves_separate_modules_with_complete_dom_contract(tmp_path):
    database = tmp_path / "acceptance-ui.sqlite3"
    api = TestClient(create_app(SqliteRunStore(database), SqliteCatalogStore(database), "token"))

    page = api.get("/ui/acceptance")
    app = api.get("/ui/assets/acceptance_app.js")
    client = api.get("/ui/assets/acceptance_api.js")
    renderer = api.get("/ui/assets/acceptance_render.js")
    styles = api.get("/ui/assets/acceptance.css")

    assert all(value.status_code == 200 for value in (page, app, client, renderer, styles))
    assert "3〜5品目 実データ受入" in page.text
    assert 'type="module" src="/ui/assets/acceptance_app.js"' in page.text
    assert 'href="/ui/selection"' in page.text
    assert 'href="/ui/acceptance"' in api.get("/ui").text
    assert 'href="/ui/acceptance"' in api.get("/ui/lifecycle").text
    assert 'href="/ui/acceptance"' in api.get("/ui/readiness").text
    assert 'href="/ui/acceptance"' in api.get("/ui/selection").text
    assert page.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    scripts = app.text + client.text + renderer.text
    assert "localStorage" not in scripts
    assert "sessionStorage" not in scripts
    assert 'request("/api/acceptance-cases")' in client.text
    assert 'request("/api/selections")' in client.text
    assert 'data-permission="ANALYZE"' in page.text
    assert 'data-permission="APPROVE"' in page.text

    ids = set(re.findall(r'id="([^"]+)"', page.text))
    assert len(ids) == len(re.findall(r'id="([^"]+)"', page.text))
    references = set(re.findall(r'(?:byId|document\.getElementById)\("([^"]+)"\)', scripts))
    assert references <= ids


def test_intake_ui_serves_paginated_modules_with_complete_dom_contract(tmp_path):
    database = tmp_path / "intake-ui.sqlite3"
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            ingestion=SqliteIngestionStore(database),
            normalization=SqliteNormalizationStore(database),
            mapping_dry_run_jobs=SqliteMappingDryRunJobStore(database),
        )
    )

    page = api.get("/ui/intake")
    app = api.get("/ui/assets/intake_app.js")
    client = api.get("/ui/assets/intake_api.js")
    forms = api.get("/ui/assets/intake_forms.js")
    renderer = api.get("/ui/assets/intake_render.js")
    styles = api.get("/ui/assets/intake.css")

    assert all(
        value.status_code == 200 for value in (page, app, client, forms, renderer, styles)
    )
    assert "原本取込・正規化" in page.text
    assert 'type="module" src="/ui/assets/intake_app.js"' in page.text
    assert 'href="/ui/intake"' in api.get("/ui").text
    assert 'href="/ui/intake"' in api.get("/ui/lifecycle").text
    assert 'href="/ui/intake"' in api.get("/ui/readiness").text
    assert 'href="/ui/intake"' in api.get("/ui/selection").text
    assert 'href="/ui/intake"' in api.get("/ui/acceptance").text
    assert page.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    scripts = app.text + client.text + forms.text + renderer.text
    assert "localStorage" not in scripts
    assert "sessionStorage" not in scripts
    assert 'request("/api/imports")' in client.text
    assert 'request("/api/mappings")' in client.text
    assert 'request("/api/mapping-dry-runs")' in client.text
    assert 'request("/api/mapping-dry-run-jobs")' in client.text
    assert "はじめてのデータ検証" in page.text
    assert "このCSVを検証" in page.text
    assert 'request("/api/mapping-dry-run-sources")' in client.text
    assert "このジョブの検証結果を表示" in page.text
    assert 'selectJob("dry_run", reportSha256)' in app.text
    assert "/row-page?" in client.text
    assert 'data-permission="ANALYZE"' in page.text
    assert 'data-permission="APPROVE"' in page.text

    ids = set(re.findall(r'id="([^"]+)"', page.text))
    assert len(ids) == len(re.findall(r'id="([^"]+)"', page.text))
    references = set(re.findall(r'(?:byId|document\.getElementById)\("([^"]+)"\)', scripts))
    assert references <= ids


def test_matching_ui_serves_audited_modular_workflow(tmp_path):
    database = tmp_path / "matching-ui.sqlite3"
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            normalization=SqliteNormalizationStore(database),
            master=SqliteMasterStore(database),
        )
    )

    page = api.get("/ui/matching")
    app = api.get("/ui/assets/matching_app.js")
    client = api.get("/ui/assets/matching_api.js")
    forms = api.get("/ui/assets/matching_forms.js")
    renderer = api.get("/ui/assets/matching_render.js")
    styles = api.get("/ui/assets/matching.css")

    assert all(
        value.status_code == 200 for value in (page, app, client, forms, renderer, styles)
    )
    assert "JAN名寄せ・商品マスター" in page.text
    assert 'type="module" src="/ui/assets/matching_app.js"' in page.text
    routes = (
        "/ui",
        "/ui/lifecycle",
        "/ui/readiness",
        "/ui/selection",
        "/ui/acceptance",
        "/ui/intake",
    )
    assert all('href="/ui/matching"' in api.get(path).text for path in routes)
    assert page.headers["cache-control"] == "no-store"
    scripts = app.text + client.text + forms.text + renderer.text
    assert "localStorage" not in scripts
    assert "sessionStorage" not in scripts
    assert 'request("/api/matching/jobs")' in client.text
    assert 'request("/api/products")' in client.text
    assert 'request("/api/matching/decisions")' in client.text
    assert 'request("/api/jan-mappings")' in client.text
    assert 'data-permission="ANALYZE"' in page.text
    assert 'data-permission="APPROVE"' in page.text

    ids = set(re.findall(r'id="([^"]+)"', page.text))
    assert len(ids) == len(re.findall(r'id="([^"]+)"', page.text))
    references = set(re.findall(r'(?:byId|document\.getElementById)\("([^"]+)"\)', scripts))
    assert references <= ids


def test_resource_cost_ui_serves_complete_admin_workflow(tmp_path):
    database = tmp_path / "resource-ui.sqlite3"
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            resource_cost=SqliteResourceCostStore(database),
        )
    )

    page = api.get("/ui/resources")
    app = api.get("/ui/assets/resource_cost_app.js")
    client = api.get("/ui/assets/resource_cost_api.js")
    renderer = api.get("/ui/assets/resource_cost_render.js")
    styles = api.get("/ui/assets/resource_cost.css")

    assert all(value.status_code == 200 for value in (page, app, client, renderer, styles))
    assert "資源・費用台帳" in page.text
    assert 'type="module" src="/ui/assets/resource_cost_app.js"' in page.text
    assert 'href="/ui"' in page.text
    routes = (
        "/ui",
        "/ui/lifecycle",
        "/ui/readiness",
        "/ui/selection",
        "/ui/acceptance",
        "/ui/intake",
        "/ui/matching",
    )
    assert all('href="/ui/resources"' in api.get(path).text for path in routes)
    assert page.headers["cache-control"] == "no-store"
    scripts = app.text + client.text + renderer.text
    assert "localStorage" not in scripts
    assert "sessionStorage" not in scripts
    assert 'request("/api/runs?limit=200")' in client.text
    assert 'request("/api/resource-unit-prices")' in client.text
    assert "/resources`" in client.text
    assert 'data-permission="MANAGE_RESOURCE"' in page.text
    assert "単価未登録" in renderer.text

    ids = set(re.findall(r'id="([^"]+)"', page.text))
    assert len(ids) == len(re.findall(r'id="([^"]+)"', page.text))
    references = set(re.findall(r'(?:byId|document\.getElementById)\("([^"]+)"\)', scripts))
    assert references <= ids
