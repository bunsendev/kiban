"""Phase 2Z: 在庫特徴CSVの不変発行台帳と再取得検証。"""

import sqlite3
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.inventory_normalization import SqliteInventoryNormalizationStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.master import SqliteMasterStore, make_jan_mapping, make_product


def _setup(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    inventory = SqliteInventoryNormalizationStore(database)
    job_id = inventory.enqueue("client-uploads/batch", "product-jan-" + "f" * 64, "バラ", "担当")
    inventory.claim()
    inventory.complete(
        job_id,
        [("2026-09-01", "4901234567894", "C01", "バラ", "5")],
        "5",
        "5",
    )
    inventory.decide(job_id, "inventory-v1", "APPROVED", "approver", "確認済み")
    adoption = inventory.current_adoption()
    master = SqliteMasterStore(database)
    product = make_product("人工商品", "approver", "試験")
    master.put_product(product)
    master.put_jan_mapping(
        make_jan_mapping(
            "4901234567894",
            product.canonical_product_id,
            "2026-01-01",
            None,
            "mapping-v1",
            "approver",
            "試験",
        )
    )
    as_of = (datetime.fromisoformat(adoption["decided_at"]) + timedelta(seconds=1)).isoformat()
    client = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            inventory_normalization=inventory,
        )
    )
    client.headers["Authorization"] = "Bearer token"
    return database, client, as_of


def test_publish_is_idempotent_audited_and_downloadable(tmp_path):
    _, client, as_of = _setup(tmp_path)
    payload = {"mapping_version": "mapping-v1", "as_of": as_of}
    first = client.post("/api/inventory-feature-exports", json=payload)
    second = client.post("/api/inventory-feature-exports", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    record = first.json()
    assert second.json()["export_id"] == record["export_id"]
    assert record["export_id"] == f"inventory-feature-{record['content_sha256']}"
    assert record["published_by"] == "local-admin"
    assert record["row_count"] == 1
    assert client.get("/api/inventory-feature-exports").json()[0] == record

    downloaded = client.get(f"/api/inventory-feature-exports/{record['export_id']}")
    assert downloaded.status_code == 200
    assert downloaded.headers["x-content-sha256"] == record["content_sha256"]
    assert downloaded.headers["x-kiban-feature-view-id"] == record["view_id"]
    assert "4901234567894" not in downloaded.text


def test_download_detects_ledger_tampering(tmp_path):
    database, client, as_of = _setup(tmp_path)
    record = client.post(
        "/api/inventory-feature-exports",
        json={"mapping_version": "mapping-v1", "as_of": as_of},
    ).json()
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE inventory_feature_exports SET content_sha256=? WHERE export_id=?",
            ("0" * 64, record["export_id"]),
        )
    response = client.get(f"/api/inventory-feature-exports/{record['export_id']}")
    assert response.status_code == 409
    assert "4901234567894" not in response.text
