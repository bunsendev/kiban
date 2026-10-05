import os

import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.runtime.api_credentials import ApiCredentials, CredentialError

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI integration")


def test_dpapi_persistence_replacement_corruption_and_delete(tmp_path):
    path = tmp_path / "credentials" / "test.dpapi"
    store = ApiCredentials(path)
    assert store.status() == {"saved": False, "available": False}
    assert store.save("sk-synthetic-first")["available"]
    assert b"sk-synthetic-first" not in path.read_bytes()
    assert ApiCredentials(path).load() == "sk-synthetic-first"
    store.save("sk-synthetic-second")
    assert ApiCredentials(path).load() == "sk-synthetic-second"
    with pytest.raises(CredentialError):
        store.save("invalid\nkey")
    assert store.load() == "sk-synthetic-second"
    path.write_bytes(b"corrupt")
    assert store.status() == {"saved": True, "available": False}
    with pytest.raises(CredentialError):
        store.load()
    assert store.delete() == {"saved": False, "available": False}
    assert not path.exists()


def test_http_never_returns_key_and_external_origin_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-profile"))
    client = TestClient(create_app(tmp_path / "data"), base_url="http://127.0.0.1")
    response = client.post("/api/ai-credentials", json={"api_key": "sk-synthetic-api"})
    assert response.json() == {"saved": True, "available": True}
    assert "sk-synthetic-api" not in client.get("/api/ai-credentials").text
    assert not list((tmp_path / "data").rglob("*.dpapi"))
    assert client.post("/api/ai-credentials", json={"api_key": "other-key"},
                       headers={"Origin": "https://outside.example"}).status_code == 403
    assert client.get("/api/ai-credentials/export").status_code == 404
    assert client.post("/api/ai-credentials/delete", json={}).status_code == 422
    removed = client.post("/api/ai-credentials/delete", json={"confirm": True})
    assert removed.json()["saved"] is False


def test_saved_key_used_server_side(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-profile"))
    app = create_app(tmp_path / "data")
    review = app.state.drop_folder.review
    review.credentials.save("sk-synthetic-saved")
    raw = "出荷日,JAN,数量\n2026/01/01,4901234567894,2\n".encode()
    (review.paths.incoming / "test.csv").write_bytes(raw)
    _, info = review.source("test.csv")

    def fake_cloud(structure, key):
        assert key == "sk-synthetic-saved"
        return {"needs_review": True}

    monkeypatch.setattr("portable.api.folder_review.suggest_cloud_structure", fake_cloud)
    assert review.suggest({"filename": "test.csv", "sha256": info["sha256"],
                           "consent": True}) == {"needs_review": True}
