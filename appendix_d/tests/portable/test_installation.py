import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.runtime.installation import create_profile, load_profile


def test_independent_installations_and_immutable_purpose(tmp_path):
    field, it = tmp_path / "field", tmp_path / "it"
    first = create_profile(field, "FIELD", "現場01")
    second = create_profile(it, "IT_TEST", "IT01")
    assert first["installation_id"] != second["installation_id"]
    assert load_profile(field) == first
    with pytest.raises(FileExistsError):
        create_profile(field, "IT_TEST", "変更")
    assert load_profile(field) == first
    with TestClient(create_app(field), base_url="http://localhost") as client:
        assert "現場利用 | 現場01" in client.get("/").text
    with TestClient(create_app(it), base_url="http://localhost") as client:
        assert "IT動作確認（テスト） | IT01" in client.get("/").text
        assert client.get("/api/runs").status_code != 500


def test_profile_input_is_validated_and_html_escaped(tmp_path):
    with pytest.raises(ValueError):
        create_profile(tmp_path, "FIELD", " ")
    create_profile(tmp_path, "IT_TEST", "<script>alert(1)</script>")
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in client.get("/").text

