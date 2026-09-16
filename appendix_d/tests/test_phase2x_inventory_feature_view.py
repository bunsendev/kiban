"""Phase 2X: 採用済み在庫の時点安全なcanonical商品接続。"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.inventory_normalization import SqliteInventoryNormalizationStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.master import (
    SqliteMasterStore,
    make_jan_mapping,
    make_product,
)


def _fixture(database):
    inventory = SqliteInventoryNormalizationStore(database)
    job_id = inventory.enqueue("client-uploads/batch", "product-jan-" + "d" * 64, "バラ", "担当")
    inventory.claim()
    inventory.complete(
        job_id,
        [("2026-09-01", "4901234567894", "C01", "バラ", "5")],
        "5",
        "5",
    )
    inventory.decide(job_id, "inventory-v1", "APPROVED", "approver", "確認済み")
    adoption = inventory.current_adoption()
    return inventory, job_id, adoption


def test_feature_view_resolves_canonical_product_after_adoption(tmp_path):
    database = tmp_path / "feature.sqlite3"
    inventory, job_id, adoption = _fixture(database)
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

    view = inventory.feature_view("mapping-v1", as_of, 10, 0)
    assert view["status"] == "READY"
    assert view["job_id"] == job_id
    assert view["source_row_count"] == 1
    assert view["resolved_row_count"] == 1
    assert view["missing_mapping_count"] == 0
    assert view["total_quantity"] == "5"
    assert view["items"] == [
        {
            "canonical_product_id": product.canonical_product_id,
            "center_id": "C01",
            "ds": "2026-09-01",
            "unit": "バラ",
            "inventory_quantity": "5",
            "available_at": adoption["decided_at"],
        }
    ]
    assert inventory.feature_view("mapping-v1", as_of, 10, 0)["view_id"] == view["view_id"]


def test_feature_view_blocks_missing_mapping_without_raw_jan(tmp_path):
    database = tmp_path / "blocked.sqlite3"
    inventory, _, adoption = _fixture(database)
    SqliteMasterStore(database)
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
    response = client.post(
        "/api/inventory-feature-views",
        json={"mapping_version": "missing-v1", "as_of": as_of},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert body["missing_mapping_count"] == 1
    assert body["items"] == []
    assert "4901234567894" not in response.text

    before = (datetime.fromisoformat(adoption["decided_at"]) - timedelta(seconds=1)).isoformat()
    response = client.post(
        "/api/inventory-feature-views",
        json={"mapping_version": "missing-v1", "as_of": before},
    )
    assert response.status_code == 422
