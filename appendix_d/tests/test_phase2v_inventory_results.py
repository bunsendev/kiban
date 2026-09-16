"""Phase 2V: 在庫正規化結果の数量照合・参照・CSV出力。"""

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.inventory_normalization import SqliteInventoryNormalizationStore
from forecast_provider.jobs import SqliteRunStore


def test_inventory_results_reconcile_paginate_and_export(tmp_path):
    database = tmp_path / "results.sqlite3"
    store = SqliteInventoryNormalizationStore(database)
    job_id = store.enqueue("client-uploads/batch", "product-jan-" + "a" * 64, "バラ", "担当")
    store.claim()
    store.complete(
        job_id,
        [
            ("2026-09-01", "4901234567894", "C01", "バラ", "5"),
            ("2026-09-02", "4901234567894", "C01", "バラ", "7"),
        ],
        "12",
        "12",
    )
    client = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            inventory_normalization=store,
        )
    )
    client.headers["Authorization"] = "Bearer token"

    results = client.get(
        f"/api/inventory-normalization-jobs/{job_id}/results?limit=1&offset=1"
    )
    assert results.status_code == 200
    assert results.json() == {
        "source_quantity": "12",
        "normalized_quantity": "12",
        "reconciled": True,
        "total": 2,
        "limit": 1,
        "offset": 1,
        "items": [
            {
                "inventory_date": "2026-09-02",
                "jan": "4901234567894",
                "center_id": "C01",
                "unit": "バラ",
                "quantity": "7",
            }
        ],
    }

    exported = client.get(f"/api/inventory-normalization-jobs/{job_id}/results.csv")
    assert exported.status_code == 200
    assert exported.content.startswith(b"\xef\xbb\xbf")
    text = exported.content.decode("utf-8-sig")
    assert "在庫日,JAN,倉庫コード,単位,数量\r\n" in text
    assert "2026-09-01,4901234567894,C01,バラ,5\r\n" in text
    assert "2026-09-02,4901234567894,C01,バラ,7\r\n" in text


def test_inventory_results_require_success_and_authentication(tmp_path):
    database = tmp_path / "pending.sqlite3"
    store = SqliteInventoryNormalizationStore(database)
    job_id = store.enqueue("client-uploads/batch", "product-jan-" + "b" * 64, "バラ", "担当")
    client = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            inventory_normalization=store,
        )
    )
    assert client.get(f"/api/inventory-normalization-jobs/{job_id}/results").status_code == 401
    client.headers["Authorization"] = "Bearer token"
    assert client.get(f"/api/inventory-normalization-jobs/{job_id}/results").status_code == 409
