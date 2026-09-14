"""Phase 2J: 初回データ検証ウィザード。"""

from datetime import datetime

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.mapping_dry_run import SqliteMappingDryRunJobStore
from forecast_provider.normalization import SqliteNormalizationStore


def _client(tmp_path):
    database = tmp_path / "phase2j.sqlite3"
    input_root = tmp_path / "input"
    input_root.mkdir()
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            normalization=SqliteNormalizationStore(database),
            mapping_dry_run_jobs=SqliteMappingDryRunJobStore(database),
            mapping_dry_run_input_root=input_root,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    return api, input_root


def test_source_catalog_returns_only_safe_csv_metadata_and_header(tmp_path):
    api, input_root = _client(tmp_path)
    nested = input_root / "batch"
    nested.mkdir()
    (nested / "shipment.csv").write_text(
        "出荷日,JANコード,商品名称\n2026/09/01,0012345678901,秘密商品\n",
        encoding="utf-8",
    )
    (input_root / "ignore.txt").write_text("秘密メモ", encoding="utf-8")

    response = api.get("/api/mapping-dry-run-sources")

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["items"][0]["source_path"] == "batch/shipment.csv"
    assert response.json()["items"][0]["columns"] == ["出荷日", "JANコード", "商品名称"]
    assert response.json()["items"][0]["encoding"] == "utf-8"
    assert "秘密商品" not in response.text
    assert "秘密メモ" not in response.text


def test_source_catalog_requires_authentication_and_reports_unconfigured(tmp_path):
    database = tmp_path / "phase2j-empty.sqlite3"
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
        )
    )
    assert api.get("/api/mapping-dry-run-sources").status_code == 401
    response = api.get(
        "/api/mapping-dry-run-sources",
        headers={"Authorization": "Bearer token"},
    )
    assert response.json() == {"configured": False, "items": []}


def test_job_timestamp_serialization_marks_naive_database_values_as_utc():
    job = SqliteMappingDryRunJobStore._job(
        {
            "job_id": "job-1",
            "source_path": "shipment.csv",
            "mapping_id": "map-" + "1" * 64,
            "requested_by": "operator",
            "status": "QUEUED",
            "sample_rows": 100,
            "requested_at": datetime(2026, 9, 14, 0, 23),
            "started_at": None,
            "finished_at": None,
            "dry_run_id": None,
            "outcome": None,
            "report_sha256": None,
            "error_code": None,
        }
    )
    assert job.requested_at == "2026-09-14T00:23:00+00:00"


def test_intake_ui_exposes_guided_validation_and_plain_language_results(tmp_path):
    api, _ = _client(tmp_path)
    page = api.get("/ui/intake")
    app = api.get("/ui/assets/intake_app.js")
    client = api.get("/ui/assets/intake_api.js")
    renderer = api.get("/ui/assets/intake_render.js")

    assert "はじめてのデータ検証" in page.text
    assert "CSVを選ぶ" in page.text
    assert "列の対応付けを選ぶ" in page.text
    assert "このCSVを検証" in page.text
    assert "新しい対応付けを作成" in page.text
    assert 'request("/api/mapping-dry-run-sources")' in client.text
    assert "window.setTimeout" in app.text
    assert "検証が完了しました。判定と修正方法を表示しています。" in app.text
    assert "CSVの保存場所" in renderer.text
    assert "対応付けに必要な列がCSVにありません" in renderer.text
    assert 'id="dry-run-submit"' in page.text
    assert "確認・修正方法" in page.text
    assert "slice(0, historyLimit)" in renderer.text
