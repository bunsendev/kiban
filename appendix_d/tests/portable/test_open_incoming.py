from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.runtime.paths import DataPaths


def test_open_fixed_folder_and_origin_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTABLE_SMOKE", "1")
    opened = []
    monkeypatch.setattr(
        "portable.api.drop_folder_routes.os.startfile", opened.append, raising=False
    )
    root = tmp_path / "Data"
    with TestClient(create_app(root), base_url="http://127.0.0.1") as client:
        assert client.post("/api/drop-folder/open", json={"path": "ignored"}).json() == {
            "status": "OPENED",
        }
        assert opened == [DataPaths(root).incoming]
        response = client.post("/api/drop-folder/open", headers={"Origin": "https://other.test"})
        assert response.status_code == 403
        assert len(opened) == 1
        assert client.get("/api/drop-folder/open").status_code == 405
        assert client.get("/field/manual").status_code == 200
        assert client.get("/field/manual.css").status_code == 200
        # Both UI entry points must serve the shared settings module and its imports.
        assert '/field/assets/detailed-settings.js' in client.get('/').text
        for asset in ('detailed-settings.js', 'settings.js', 'operations.js', 'api.js'):
            result = client.get('/field/assets/' + asset)
            assert result.status_code == 200
            assert 'javascript' in result.headers['content-type']
        assert "settings(ctx" in client.get('/field/assets/upload.js').text


def test_open_error_is_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTABLE_SMOKE", "1")

    def failure(path):
        raise OSError("private path details")

    monkeypatch.setattr("portable.api.drop_folder_routes.os.startfile", failure, raising=False)
    with TestClient(create_app(tmp_path / "Data"), base_url="http://127.0.0.1") as client:
        response = client.post("/api/drop-folder/open")
        assert response.status_code == 503
        assert "private path" not in response.text
