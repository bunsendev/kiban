"""Phase 2P: 在庫CSV構造の一括診断。"""

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.mapping_dry_run import SqliteMappingDryRunJobStore
from forecast_provider.normalization import SqliteNormalizationStore


def _zip() -> bytes:
    header = (
        "ヘッダ入荷日,明細入荷日,商品コード,商品名,明細資産数量,内訳資産数量,"
        "明細倉庫コード,ヘッダ倉庫コード,明細荷姿単位コード,内訳荷姿単位コード\n"
    ).encode("cp932")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("在庫データ/加須日時在庫_1.csv", header)
        archive.writestr("在庫データ/加須日時在庫_2.csv", header + b"\n")
        archive.writestr("在庫データ/加須日時出荷_1.csv", b"shipment\n")
    return output.getvalue()


def _client(tmp_path: Path) -> TestClient:
    database = tmp_path / "profile.sqlite3"
    input_root = tmp_path / "input"
    input_root.mkdir()
    client = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            normalization=SqliteNormalizationStore(database),
            mapping_dry_run_jobs=SqliteMappingDryRunJobStore(database),
            mapping_dry_run_input_root=input_root,
        )
    )
    client.headers["Authorization"] = "Bearer token"
    return client


def test_inventory_profile_reports_coverage_and_ambiguity_without_rows(tmp_path):
    client = _client(tmp_path)
    uploaded = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=data.zip", content=_zip()
    ).json()

    response = client.post(
        "/api/inventory-structure-profiles",
        json={"source_prefix": uploaded["source_prefix"]},
    )

    assert response.status_code == 200
    profile = response.json()
    assert profile["file_count"] == 2
    assert profile["header_pattern_count"] == 1
    assert "QUANTITY_COLUMN_AMBIGUOUS" in profile["issues"]
    assert "JAN_COLUMN_MISSING" in profile["issues"]
    assert profile["field_candidates"]["product_code"][0]["file_count"] == 2
    assert "shipment" not in response.text


def test_inventory_profile_rejects_prefix_without_inventory_csv(tmp_path):
    client = _client(tmp_path)
    response = client.post("/api/inventory-structure-profiles", json={"source_prefix": "missing"})
    assert response.status_code == 422


def test_intake_ui_exposes_inventory_structure_diagnosis(tmp_path):
    client = _client(tmp_path)
    page = client.get("/ui/intake").text
    app = client.get("/ui/assets/intake_app.js").text
    assert "在庫CSVを一括診断" in page
    assert "createInventoryStructureProfile" in app
