"""Phase 2U: 在庫全件正規化job。"""

import io
import zipfile

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.inventory_normalization import (
    InventoryNormalizationProcessor,
    SqliteInventoryNormalizationStore,
)
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.mapping_dry_run import SqliteMappingDryRunJobStore
from forecast_provider.normalization import SqliteNormalizationStore


def test_api_worker_aggregates_inventory_daily_quantities(tmp_path):
    database = tmp_path / "inventory.sqlite3"
    root = tmp_path / "input"
    root.mkdir()
    inventory = SqliteInventoryNormalizationStore(database)
    client = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            normalization=SqliteNormalizationStore(database),
            mapping_dry_run_jobs=SqliteMappingDryRunJobStore(database),
            mapping_dry_run_input_root=root,
            inventory_normalization=inventory,
        )
    )
    client.headers["Authorization"] = "Bearer token"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "在庫データ/日時在庫_20260901.csv",
            (
                "商品コード,商品名,明細バラ数,明細倉庫コード\n"
                "P01,秘密商品,2,C01\nP01,秘密商品,3,C01\nP01,秘密商品,-1,C01\n"
            ).encode("cp932"),
        )
        archive.writestr(
            "在庫データ/日時在庫_20261340.csv",
            (
                "商品コード,商品名,明細バラ数,明細倉庫コード\n"
                "P01,秘密商品,7,C01\n"
            ).encode("cp932"),
        )
    prefix = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=data.zip", content=output.getvalue()
    ).json()["source_prefix"]
    mapping_report = client.post(
        "/api/product-jan-mappings",
        params={"source_prefix": prefix},
        content=(
            "商品コード,商品名,JAN,確認メモ\r\nP01,秘密商品,4901234567894,確認済み\r\n"
        ).encode(),
    ).json()

    created = client.post(
        "/api/inventory-normalization-jobs",
        json={
            "source_prefix": prefix,
            "product_mapping_id": mapping_report["mapping_id"],
            "unit_value": "バラ",
        },
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    assert InventoryNormalizationProcessor(inventory, root).process_next() is True

    job = client.get(f"/api/inventory-normalization-jobs/{job_id}").json()
    assert job["status"] == "SUCCEEDED"
    assert job["processed_file_count"] == 2
    assert job["accepted_row_count"] == 2
    assert job["quarantined_row_count"] == 2
    assert job["reason_counts"] == {
        "INVENTORY_DATE_INVALID": 1,
        "QUANTITY_INVALID": 1,
    }
    values = inventory.list_values(job_id)
    assert values == [
        {
            "inventory_date": "2026-09-01",
            "jan": "4901234567894",
            "center_id": "C01",
            "unit": "バラ",
            "quantity": "5",
        }
    ]
    assert "秘密商品" not in str(job)


def test_inventory_job_api_requires_authentication(tmp_path):
    database = tmp_path / "auth.sqlite3"
    store = SqliteInventoryNormalizationStore(database)
    client = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            inventory_normalization=store,
        )
    )
    assert client.get("/api/inventory-normalization-jobs/missing").status_code == 401
