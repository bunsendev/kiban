"""Phase 2Y: 在庫特徴ビューの決定的CSV発行。"""

import hashlib
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.inventory_normalization import SqliteInventoryNormalizationStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.master import SqliteMasterStore, make_jan_mapping, make_product


def _client(tmp_path, *, mapped=True):
    database = tmp_path / "export.sqlite3"
    inventory = SqliteInventoryNormalizationStore(database)
    job_id = inventory.enqueue("client-uploads/batch", "product-jan-" + "e" * 64, "バラ", "担当")
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
    if mapped:
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
    return client, as_of


def test_feature_export_is_deterministic_bom_csv_with_checksum(tmp_path):
    client, as_of = _client(tmp_path)
    params = {"mapping_version": "mapping-v1", "as_of": as_of}
    first = client.get("/api/inventory-feature-views.csv", params=params)
    second = client.get("/api/inventory-feature-views.csv", params=params)

    assert first.status_code == 200
    assert first.content == second.content
    assert first.content.startswith(b"\xef\xbb\xbf")
    assert first.headers["x-content-sha256"] == hashlib.sha256(first.content).hexdigest()
    assert first.headers["x-kiban-feature-view-id"] == second.headers[
        "x-kiban-feature-view-id"
    ]
    text = first.content.decode("utf-8-sig")
    assert "feature_view_id,canonical_product_id,center_id,ds,unit," in text
    assert ",C01,2026-09-01,バラ,5," in text
    assert "4901234567894" not in text


def test_feature_export_rejects_blocked_view(tmp_path):
    client, as_of = _client(tmp_path, mapped=False)
    response = client.get(
        "/api/inventory-feature-views.csv",
        params={"mapping_version": "missing-v1", "as_of": as_of},
    )
    assert response.status_code == 409
    assert "4901234567894" not in response.text
