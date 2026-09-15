"""Phase 2R: 在庫商品コードとJANの対応準備。"""

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
    database = tmp_path / "bridge.sqlite3"
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


def _zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "在庫データ/日時出荷_20260901.csv",
            "商品コード,商品名,JAN\n,商品A,4900000000001\n".encode("cp932"),
        )
        archive.writestr(
            "在庫データ/日時在庫_20260901.csv",
            "商品コード,商品名,明細バラ数\nP01,商品A,2\nP02,商品B,3\n".encode("cp932"),
        )
    return output.getvalue()


def test_analysis_requires_external_mapping_and_template_contains_products(tmp_path):
    client = _client(tmp_path)
    uploaded = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=data.zip", content=_zip()
    ).json()
    prefix = uploaded["source_prefix"]

    analysis = client.post(
        "/api/product-jan-bridge-analysis", json={"source_prefix": prefix}
    ).json()
    assert analysis["status"] == "EXTERNAL_MAPPING_REQUIRED"
    assert analysis["shipment_code_jan_pair_rows"] == 0
    assert analysis["inventory_distinct_product_codes"] == 2

    template = client.get("/api/product-jan-bridge-template.csv", params={"source_prefix": prefix})
    assert template.status_code == 200
    assert template.content.startswith(b"\xef\xbb\xbf")
    text = template.content.decode("utf-8-sig")
    assert "商品コード,商品名,JAN,確認メモ" in text
    assert "P01,商品A,," in text
    assert "4900000000001" not in text


def test_bridge_endpoints_require_authentication(tmp_path):
    client = _client(tmp_path)
    client.headers.clear()
    assert (
        client.post("/api/product-jan-bridge-analysis", json={"source_prefix": "x"}).status_code
        == 401
    )
    assert client.get("/api/product-jan-bridge-template.csv?source_prefix=x").status_code == 401
