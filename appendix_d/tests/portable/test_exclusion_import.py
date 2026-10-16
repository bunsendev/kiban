import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.api.document_ai import DocumentError
from portable.api.exclusion_import import preview_list
from portable.runtime.paths import DataPaths


def test_csv_encodings_and_invalid_jan_retained(tmp_path):
    for encoding in ("utf-8-sig", "cp932"):
        raw = "JAN,商品名,理由\n4901234567894,人工商品,対象外\n567894,未確定商品,確認中\n".encode(
            encoding
        )
        result = preview_list(raw, "任意.csv", DataPaths(tmp_path))
        assert result["method"] == "local"
        assert len(result["products"]) == 2
        assert result["products"][0]["issue"] == ""
        assert result["products"][1]["jan"] == "567894"
        assert result["products"][1]["issue"]


def test_json_release_and_conflicts(tmp_path):
    value = {
        "format": "bunsen-product-exclusions-v1",
        "products": [{"jan": "4901234567894", "exclude": False}],
    }
    result = preview_list(json.dumps(value).encode(), "list.json", DataPaths(tmp_path))
    assert result["products"][0]["exclude"] is False
    value["products"].append({"jan": "4901234567894", "exclude": True})
    with pytest.raises(DocumentError, match="重複"):
        preview_list(json.dumps(value).encode(), "list.json", DataPaths(tmp_path))


def test_image_requires_consent_and_retains_partial_candidates(tmp_path, monkeypatch):
    import portable.api.exclusion_import as adapter

    with pytest.raises(DocumentError, match="同意"):
        preview_list(b"image", "list.png", DataPaths(tmp_path))
    monkeypatch.setattr(adapter.ApiCredentials, "load", lambda self: "synthetic-key")

    def fake_extract(raw, key, *, purpose):
        assert purpose == "exclusions" and key == "synthetic-key"
        return {"complete": False, "rows": [{"jan": "", "product_name": "読めた名前"}]}

    monkeypatch.setattr(adapter, "extract", fake_extract)
    result = preview_list(b"image", "list.png", DataPaths(tmp_path), consent=True)
    assert result["complete"] is False and result["products"][0]["issue"]


def test_native_pdf_no_external_send(tmp_path, monkeypatch):
    import portable.api.exclusion_import as adapter

    monkeypatch.setattr(
        adapter,
        "extract_inventory",
        lambda raw: {"complete": True, "rows": [{"jan": "4901234567894", "exclude": False}]},
    )
    monkeypatch.setattr(adapter, "extract", lambda *args, **kwargs: pytest.fail("external call"))
    assert preview_list(b"pdf", "list.pdf", DataPaths(tmp_path))["method"] == "local"


def test_preview_does_not_register_and_registration_links_source(tmp_path):
    app = create_app(tmp_path / "Data")
    client = TestClient(app, base_url="http://127.0.0.1")
    raw = b"JAN,product_name\n4901234567894,Synthetic\n"
    response = client.post(
        "/api/product-exclusions/preview", content=raw, headers={"X-File-Name": "list.csv"}
    )
    assert response.status_code == 200
    result = response.json()
    assert client.get("/api/product-exclusions").json() == []
    value = {
        "actor": "tester",
        "products": result["products"],
        "source_sha256": result["source_sha256"],
    }
    assert client.post("/api/product-exclusions", json=value).status_code == 422
    value["confirmed"] = True
    assert client.post("/api/product-exclusions", json=value).status_code == 200
    with sqlite3.connect(app.state.documents.exclusions.path) as db:
        assert db.execute("SELECT original FROM previews").fetchone()[0] == raw
        assert db.execute("SELECT sha FROM event_sources").fetchone()[0] == result["source_sha256"]


def test_malformed_csv_is_validation_error(tmp_path):
    client = TestClient(create_app(tmp_path / "Data"), base_url="http://127.0.0.1")
    response = client.post(
        "/api/product-exclusions/preview",
        content=b'JAN\n"unclosed',
        headers={"X-File-Name": "list.csv"},
    )
    assert response.status_code == 422


def test_json_master_completion_keeps_exclusion(tmp_path):
    value = {
        "format": "bunsen-product-exclusions-v1",
        "products": [{"product_name": "Synthetic", "exclude": True}],
    }
    master = {
        "version": "v1",
        "products": [
            {
                "jan": "4901234567894",
                "product_name": "Synthetic",
                "product_code": "A1",
                "cell": "A1",
            }
        ],
    }
    result = preview_list(
        json.dumps(value).encode(), "list.json", DataPaths(tmp_path), master=master
    )
    assert result["products"][0]["jan"] == "4901234567894"
    assert result["products"][0]["exclude"] is True
