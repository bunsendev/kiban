import hashlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.api.business_archive import ArchiveError
from portable.api.folder_csv import bundle_csv
from portable.api.folder_review import FolderReview, describe
from portable.runtime.paths import DataPaths

RAW = "日付,識別番号,出庫数\n2026/02/04,4901234567894,2\n".encode()


def setup(tmp_path):
    paths = DataPaths(tmp_path)
    paths.incoming.mkdir(parents=True)
    (paths.incoming / "a.csv").write_bytes(RAW)
    return paths, FolderReview(paths)


def approval():
    return {"filename": "a.csv", "sha256": hashlib.sha256(RAW).hexdigest(),
            "actor": "テスト担当者", "kind": "shipment",
            "mapping": {"出荷日": "日付", "JAN": "識別番号", "数量": "出庫数"},
            "center": "神戸", "day": "2026-02-04", "remember": True}


def test_confirmed_mapping_preserves_original_and_audit(tmp_path):
    paths, service = setup(tmp_path)
    saved = service.approve(approval())
    raw, originals = bundle_csv([paths.incoming / "a.csv"], service.transform)
    assert (paths.incoming / "a.csv").read_bytes() == RAW
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read("Originals/a.csv.source") == RAW
        assert json.loads(archive.read("Approvals/a.csv.json")) == saved
        assert "神戸" in archive.read("a.csv").decode("utf-8-sig")
    assert originals[0][1] == hashlib.sha256(RAW).hexdigest()


def test_reuse_columns_but_never_fixed_date_or_warehouse(tmp_path):
    _, service = setup(tmp_path)
    service.approve(approval())
    other = RAW.replace(b"2026/02/04", b"2026/02/05")
    reused = service.prior(describe(other))
    assert reused["mapping"] == approval()["mapping"]
    assert reused["center"] == reused["day"] == ""
    assert reused["reused"] is True


def test_stale_or_invented_mapping_rejected(tmp_path):
    paths, service = setup(tmp_path)
    value = approval()
    value["mapping"]["数量"] = "架空の列"
    with pytest.raises(ArchiveError):
        service.approve(value)
    (paths.incoming / "a.csv").write_bytes(RAW + b"\n")
    with pytest.raises(ArchiveError, match="変更"):
        service.approve(approval())
    with pytest.raises(ArchiveError):
        service.source("../a.csv")


def test_ai_only_receives_headers_and_cannot_approve(tmp_path, monkeypatch):
    _, service = setup(tmp_path)
    calls = []

    def suggest(structure, api_key):
        calls.append((structure, api_key))
        return {"kind": "SHIPMENT_ACTUAL", "needs_review": True}

    monkeypatch.setattr("portable.api.folder_review.suggest_cloud_structure", suggest)
    payload = {**approval(), "consent": True, "api_key": "test-key"}
    assert service.suggest(payload)["needs_review"] is True
    assert calls == [({"headers": ["日付", "識別番号", "出庫数"], "value_types": {}}, "test-key")]
    assert service.prior(describe(RAW)) is None
    assert b"test-key" not in service.db_path.read_bytes()
    with pytest.raises(ArchiveError):
        service.suggest({**payload, "consent": False})


def test_http_approve_then_folder_analysis(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1")
    (tmp_path / "Incoming" / "a.csv").write_bytes(RAW)
    candidates = client.get("/api/drop-folder/review").json()
    assert candidates[0]["approval"] is None
    response = client.post("/api/drop-folder/approve", json=approval())
    assert response.status_code == 200, response.text
    response = client.post("/api/drop-folder/scan")
    assert response.json()["handled"][0]["status"] == "PROCESSED"
    assert client.get("/field/assets/folder-review.js").status_code == 200
    assert client.post("/api/drop-folder/approve", json={}).status_code == 422
