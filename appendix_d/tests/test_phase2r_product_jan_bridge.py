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
            "商品コード,商品名,JAN\n,商品A,4901234567894\n".encode("cp932"),
        )
        archive.writestr(
            "在庫データ/日時在庫_20260901.csv",
            "商品コード,商品名,明細バラ数\nP01,商品A,2\nP02,商品B,3\n".encode("cp932"),
        )
    return output.getvalue()


def test_analysis_proposes_unique_name_candidate_but_requires_review(tmp_path):
    client = _client(tmp_path)
    uploaded = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=data.zip", content=_zip()
    ).json()
    prefix = uploaded["source_prefix"]

    analysis = client.post(
        "/api/product-jan-bridge-analysis", json={"source_prefix": prefix}
    ).json()
    assert analysis["status"] == "CANDIDATE_REVIEW_REQUIRED"
    assert analysis["shipment_code_jan_pair_rows"] == 0
    assert analysis["inventory_distinct_product_codes"] == 2
    assert analysis["candidate_unique_products"] == 1
    assert analysis["candidate_ambiguous_products"] == 0
    assert analysis["candidate_missing_products"] == 1

    template = client.get("/api/product-jan-bridge-template.csv", params={"source_prefix": prefix})
    assert template.status_code == 200
    assert template.content.startswith(b"\xef\xbb\xbf")
    text = template.content.decode("utf-8-sig")
    assert "商品コード,商品名,JAN,確認メモ" in text
    assert "P01,商品A,4901234567894,候補（商品名完全一致・要確認）" in text
    assert "P02,商品B,,候補なし" in text


def test_bridge_endpoints_require_authentication(tmp_path):
    client = _client(tmp_path)
    client.headers.clear()
    assert (
        client.post("/api/product-jan-bridge-analysis", json={"source_prefix": "x"}).status_code
        == 401
    )
    assert client.get("/api/product-jan-bridge-template.csv?source_prefix=x").status_code == 401


def test_mapping_upload_validates_coverage_and_saves_content_addressed_file(tmp_path):
    client = _client(tmp_path)
    uploaded = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=data.zip", content=_zip()
    ).json()
    prefix = uploaded["source_prefix"]
    incomplete = "商品コード,商品名,JAN,確認メモ\r\nP01,商品A,123,\r\n".encode()

    report = client.post(
        "/api/product-jan-mappings",
        params={"source_prefix": prefix},
        content=incomplete,
    ).json()
    assert report["status"] == "CORRECTION_REQUIRED"
    assert report["issues"]["invalid_jans"] == 1
    assert report["issues"]["missing_product_codes"] == 1
    assert report["mapping_id"] is None

    complete = (
        "商品コード,商品名,JAN,確認メモ\r\n"
        "P01,商品A,4901234567894,確認済み\r\n"
        "P02,商品B,4006381333931,確認済み\r\n"
    ).encode()
    report = client.post(
        "/api/product-jan-mappings",
        params={"source_prefix": prefix},
        content=complete,
    ).json()
    assert report["status"] == "READY"
    assert report["completed_product_count"] == 2
    assert report["confirmed_product_count"] == 2
    mapping_id = report["mapping_id"]
    assert mapping_id.startswith("product-jan-")
    saved = tmp_path / "input" / "product-jan-mappings" / f"{mapping_id}.csv"
    assert saved.is_file()
    assert saved.read_bytes().startswith(b"\xef\xbb\xbf")


def test_prefilled_candidate_is_not_saved_until_human_confirmation(tmp_path):
    client = _client(tmp_path)
    uploaded = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=data.zip", content=_zip()
    ).json()
    prefix = uploaded["source_prefix"]
    candidate = client.get(
        "/api/product-jan-bridge-template.csv", params={"source_prefix": prefix}
    ).content

    report = client.post(
        "/api/product-jan-mappings", params={"source_prefix": prefix}, content=candidate
    ).json()

    assert report["status"] == "CORRECTION_REQUIRED"
    assert report["completed_product_count"] == 1
    assert report["confirmed_product_count"] == 0
    assert report["issues"]["unconfirmed_jans"] == 1
    assert report["issues"]["blank_jans"] == 1
    assert report["mapping_id"] is None


def test_candidate_scan_does_not_miss_rows_after_sample_limit(tmp_path):
    client = _client(tmp_path)
    output = io.BytesIO()
    filler = "\n".join(
        f",対象外{i},4900000000001" for i in range(100)
    )
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "在庫データ/日時出荷_20260901.csv",
            ("商品コード,商品名,JAN\n" + filler + "\n,対象商品,4006381333931\n").encode(
                "cp932"
            ),
        )
        archive.writestr(
            "在庫データ/日時在庫_20260901.csv",
            "商品コード,商品名,明細バラ数\nP01,対象商品,2\n".encode("cp932"),
        )
    uploaded = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=data.zip", content=output.getvalue()
    ).json()

    analysis = client.post(
        "/api/product-jan-bridge-analysis",
        json={"source_prefix": uploaded["source_prefix"]},
    ).json()

    assert analysis["candidate_unique_products"] == 1
    assert analysis["candidate_missing_products"] == 0


def test_ambiguous_candidate_lists_options_without_selecting_one(tmp_path):
    client = _client(tmp_path)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "在庫データ/日時出荷_20260901.csv",
            (
                "商品コード,商品名,JAN\n"
                ",商品A,4901234567894\n"
                ",商品A,4006381333931\n"
            ).encode("cp932"),
        )
        archive.writestr(
            "在庫データ/日時在庫_20260901.csv",
            "商品コード,商品名,明細バラ数\nP01,商品A,2\n".encode("cp932"),
        )
    uploaded = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=data.zip", content=output.getvalue()
    ).json()

    template = client.get(
        "/api/product-jan-bridge-template.csv",
        params={"source_prefix": uploaded["source_prefix"]},
    ).content.decode("utf-8-sig")

    assert "P01,商品A,," in template
    assert "複数候補（要確認）" in template
    assert "4006381333931 / 4901234567894" in template


def test_direct_product_code_candidate_is_proposed_even_when_name_differs(tmp_path):
    client = _client(tmp_path)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "在庫データ/日時出荷_20260901.csv",
            "商品コード,商品名,JAN\nP01,旧商品名,4901234567894\n".encode("cp932"),
        )
        archive.writestr(
            "在庫データ/日時在庫_20260901.csv",
            "商品コード,商品名,明細バラ数\nP01,現商品名,2\n".encode("cp932"),
        )
    uploaded = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=data.zip", content=output.getvalue()
    ).json()

    template = client.get(
        "/api/product-jan-bridge-template.csv",
        params={"source_prefix": uploaded["source_prefix"]},
    ).content.decode("utf-8-sig")

    assert "P01,現商品名,4901234567894,候補（出荷商品コード一致・要確認）" in template
