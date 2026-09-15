"""Phase 2T: JAN対応表を使う在庫正規化preview。"""

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.mapping_dry_run import SqliteMappingDryRunJobStore
from forecast_provider.normalization import SqliteNormalizationStore


def _client(tmp_path: Path) -> TestClient:
    database = tmp_path / "preview.sqlite3"
    root = tmp_path / "input"
    root.mkdir()
    client = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            normalization=SqliteNormalizationStore(database),
            mapping_dry_run_jobs=SqliteMappingDryRunJobStore(database),
            mapping_dry_run_input_root=root,
        )
    )
    client.headers["Authorization"] = "Bearer token"
    return client


def _upload(client: TestClient, inventory_name: str, rows: str) -> tuple[str, str]:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            f"在庫データ/{inventory_name}",
            ("商品コード,商品名,明細バラ数,明細倉庫コード\n" + rows).encode("cp932"),
        )
    prefix = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=data.zip", content=output.getvalue()
    ).json()["source_prefix"]
    mapping = ("商品コード,商品名,JAN,確認メモ\r\nP01,商品A,4901234567894,確認済み\r\n").encode()
    report = client.post(
        "/api/product-jan-mappings", params={"source_prefix": prefix}, content=mapping
    ).json()
    return prefix, report["mapping_id"]


def test_preview_accepts_inventory_rows_without_returning_values(tmp_path):
    client = _client(tmp_path)
    prefix, mapping_id = _upload(client, "日時在庫_20260901.csv", "P01,秘密商品,12,秘密倉庫\n")

    response = client.post(
        "/api/inventory-normalization-previews",
        json={
            "source_prefix": prefix,
            "product_mapping_id": mapping_id,
            "unit_value": "バラ",
            "sample_rows": 100,
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["outcome"] == "READY_FOR_INVENTORY_NORMALIZATION"
    assert report["accepted_rows"] == 1
    assert report["quarantined_rows"] == 0
    assert "秘密商品" not in response.text
    assert "秘密倉庫" not in response.text
    assert mapping_id not in response.text.replace(report["product_mapping_id"], "")


def test_preview_counts_fixed_quarantine_reasons(tmp_path):
    client = _client(tmp_path)
    prefix, mapping_id = _upload(
        client,
        "日時在庫_invalid.csv",
        "P01,商品A,-1,\n,商品X,abc,C01\n",
    )
    report = client.post(
        "/api/inventory-normalization-previews",
        json={
            "source_prefix": prefix,
            "product_mapping_id": mapping_id,
            "unit_value": "バラ",
            "sample_rows": 100,
        },
    ).json()
    assert report["outcome"] == "REVIEW_REQUIRED"
    assert report["quarantined_rows"] == 2
    assert report["reason_counts"] == {
        "CENTER_MISSING": 1,
        "INVENTORY_DATE_INVALID": 2,
        "PRODUCT_MAPPING_MISSING": 1,
        "QUANTITY_INVALID": 2,
    }
