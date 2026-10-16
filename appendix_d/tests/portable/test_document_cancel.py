from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from test_documents import row, setup

from portable.api.document_ai import DocumentError


def test_cancel_during_api_discards_late_result_and_resume_is_safe(tmp_path, monkeypatch):
    client, service, identifier = setup(tmp_path, monkeypatch)
    started, finish = Event(), Event()

    def slow(*args, **kwargs):
        started.set()
        assert finish.wait(5)
        return {"rows": [row()], "complete": True}

    monkeypatch.setattr("portable.api.document_intake.extract", slow)
    monkeypatch.setattr("portable.api.document_intake.page_source",
                        lambda raw, page: (raw, "", 2))
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(service.read, identifier, True, page=1)
        assert started.wait(5)
        try:
            result = client.post(f"/api/documents/{identifier}/cancel", json={})
            assert result.status_code == 200
            assert result.json()["cancelled"] is True
            assert result.json()["extraction"] is None
            assert client.post(f"/api/documents/{identifier}/resume", json={}).status_code == 200
        finally:
            finish.set()
        with pytest.raises(DocumentError, match="取りやめ"):
            pending.result(timeout=5)
    assert service.get(identifier)["extraction"] is None
    with service.db() as db:
        assert db.execute("SELECT COUNT(*) FROM document_pages").fetchone()[0] == 0
    assert service.read(identifier, True)["extraction"] is not None
    assert [v["status"] for v in service.history(identifier)[:2]] == ["cancelled", "resumed"]


def test_cancel_keeps_saved_result_and_blocks_approval_until_resume(tmp_path, monkeypatch):
    client, service, identifier = setup(tmp_path, monkeypatch)
    first = service.read(identifier, True)
    url = f"/api/documents/{identifier}"
    client.post(url + "/cancel", json={})
    assert service.get(identifier)["extraction"] == first["extraction"]
    with pytest.raises(DocumentError, match="取りやめ"):
        service.read(identifier, True, retry=True)
    value = {"actor": "人工", "confirmed": True, "rows": [{**row(), "case_factor": "1"}]}
    assert client.post(url + "/approve", json=value).status_code == 422
    client.post(url + "/resume", json={})
    value["revision"] = first["extraction"]["revision"]
    assert client.post(url + "/approve", json=value).status_code == 200
    assert client.post(url + "/cancel", json={}).status_code == 422
    assert service.get(identifier)["approval"] is not None
