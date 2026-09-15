"""Phase 2L: クライアントのupload、分析、結果確認フロー。"""

import asyncio
import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.mapping_dry_run import (
    MappingDryRunSourceUploader,
    SourceUploadError,
    SqliteMappingDryRunJobStore,
)
from forecast_provider.normalization import SqliteNormalizationStore, make_mapping


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    database = tmp_path / "phase2l.sqlite3"
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
    return client, input_root


def test_upload_saves_new_csv_and_lists_only_safe_metadata(tmp_path):
    client, input_root = _client(tmp_path)
    body = "出荷日,JANコード,出荷数量\n2026/09/14,0012345678901,3\n".encode()

    response = client.post(
        "/api/mapping-dry-run-uploads?filename=shipment.csv",
        content=body,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 201
    uploaded = response.json()
    assert uploaded["filename"] == "shipment.csv"
    assert uploaded["uploaded_by"] == "local-admin"
    assert uploaded["source_path"].startswith("client-uploads/")
    assert (input_root / uploaded["source_path"]).read_bytes() == body
    catalog = client.get("/api/mapping-dry-run-sources").json()
    item = next(
        value for value in catalog["items"] if value["source_path"] == uploaded["source_path"]
    )
    assert item["columns"] == ["出荷日", "JANコード", "出荷数量"]
    assert "0012345678901" not in client.get("/api/mapping-dry-run-sources").text


def test_upload_rejects_non_csv_empty_and_unauthenticated(tmp_path):
    client, input_root = _client(tmp_path)
    assert (
        client.post("/api/mapping-dry-run-uploads?filename=data.txt", content=b"x").status_code
        == 422
    )
    assert (
        client.post("/api/mapping-dry-run-uploads?filename=data.csv", content=b"").status_code
        == 422
    )
    assert not list(input_root.rglob("*.csv"))
    assert (
        TestClient(client.app)
        .post("/api/mapping-dry-run-uploads?filename=data.csv", content=b"x")
        .status_code
        == 401
    )


def test_upload_rejects_windows_invalid_or_reserved_filename(tmp_path):
    client, input_root = _client(tmp_path)
    for filename in ("CON.csv", "bad:name.csv", "trailing.csv."):
        response = client.post(f"/api/mapping-dry-run-uploads?filename={filename}", content=b"x")
        assert response.status_code == 422
    assert not list(input_root.rglob("*"))


def test_streaming_limit_removes_partial_file(tmp_path):
    input_root = tmp_path / "input"
    input_root.mkdir()
    uploader = MappingDryRunSourceUploader(input_root, max_bytes=4)

    async def chunks():
        yield b"123"
        yield b"45"

    try:
        asyncio.run(uploader.save("data.csv", chunks()))
    except SourceUploadError as exc:
        assert "4 bytes以下" in str(exc)
    else:
        raise AssertionError("SourceUploadErrorが必要です")
    assert not list(input_root.rglob("*"))


def test_intake_ui_exposes_upload_analyze_result_flow(tmp_path):
    client, _ = _client(tmp_path)
    page = client.get("/ui/intake").text
    app = client.get("/ui/assets/intake_app.js").text
    api = client.get("/ui/assets/intake_api.js").text

    assert "UPLOAD → ANALYZE → RESULT" in page
    assert "CSVをアップロード" in page
    assert "このCSVを検証・分析" in page
    assert 'id="upload-file" type="file"' in page
    assert "uploadMappingDryRunSource(file)" in app
    assert "request(`/api/mapping-dry-run-uploads?filename=${filename}`" in api


def _zip(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return output.getvalue()


def test_zip_upload_registers_all_csv_files_as_one_batch(tmp_path):
    client, input_root = _client(tmp_path)
    body = _zip(
        {
            "在庫データ/在庫.csv": "日付,JANコード,在庫数量\n2026/09/14,001,3\n".encode(),
            "在庫データ/出荷.csv": "出荷日,JANコード,出荷数量\n2026/09/14,001,1\n".encode(),
        }
    )

    response = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=batch.zip",
        content=body,
        headers={"Content-Type": "application/zip"},
    )

    assert response.status_code == 201
    uploaded = response.json()
    assert uploaded["file_count"] == 2
    assert uploaded["uploaded_by"] == "local-admin"
    batch = input_root / uploaded["source_prefix"]
    assert len(list(batch.rglob("*.csv"))) == 2
    assert not list(batch.rglob("*.zip"))
    exact = client.get(
        "/api/mapping-dry-run-sources", params={"source_path": uploaded["first_source_path"]}
    ).json()
    assert exact["items"][0]["source_path"] == uploaded["first_source_path"]


def test_zip_upload_rejects_traversal_and_non_csv_atomically(tmp_path):
    client, input_root = _client(tmp_path)
    for entries in ({"../escape.csv": b"x"}, {"data.csv": b"x", "memo.txt": b"x"}):
        response = client.post(
            "/api/mapping-dry-run-bulk-uploads?filename=batch.zip",
            content=_zip(entries),
        )
        assert response.status_code == 422
    assert not list(input_root.rglob("*.csv"))


def test_intake_ui_accepts_zip_bulk_upload(tmp_path):
    client, _ = _client(tmp_path)
    page = client.get("/ui/intake").text
    app = client.get("/ui/assets/intake_app.js").text
    api = client.get("/ui/assets/intake_api.js").text

    assert "CSV・ZIPをアップロード" in page
    assert 'accept=".csv,.zip,text/csv,application/zip"' in page
    assert "uploadMappingDryRunBatch(file)" in app
    assert "loadMappingDryRunSource(uploadedPath)" in app
    assert "/api/mapping-dry-run-bulk-uploads?filename=" in api


def test_zip_batch_selects_shipments_and_exports_results(tmp_path):
    client, _ = _client(tmp_path)
    mapping = SqliteNormalizationStore(tmp_path / "phase2l.sqlite3").put_mapping
    value = make_mapping(
        {
            "date_column": "出荷日",
            "jan_column": "JAN",
            "product_name_column": "商品名",
            "quantity_column": "数量",
            "unit_value": "個",
            "center_column": "倉庫コード",
            "date_formats": ["%Y/%m/%d"],
            "allowed_units": ["個"],
            "availability_mode": "ASSUMED",
            "file_mode": "FULL",
        }
    )
    mapping(value)
    uploaded = client.post(
        "/api/mapping-dry-run-bulk-uploads?filename=batch.zip",
        content=_zip(
            {
                "在庫データ/出荷_01.csv": b"x",
                "在庫データ/在庫_01.csv": b"x",
            }
        ),
    ).json()

    created = client.post(
        "/api/mapping-dry-run-batches",
        json={
            "source_prefix": uploaded["source_prefix"],
            "mapping_id": value.mapping_id,
            "sample_rows": 100,
        },
    )
    assert created.status_code == 202
    batch = client.get(f"/api/mapping-dry-run-batches/{created.json()['id']}").json()
    assert batch["selected_count"] == 1
    assert batch["excluded_count"] == 1
    assert batch["jobs"][0]["source_path"].endswith("出荷_01.csv")
    result = client.get(f"/api/mapping-dry-run-batches/{batch['batch_id']}/results.csv")
    assert result.status_code == 200
    assert result.content.startswith(b"\xef\xbb\xbf")
