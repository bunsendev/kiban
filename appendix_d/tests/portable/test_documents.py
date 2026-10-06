import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from portable.api import document_ai
from portable.api.app import create_app
from portable.api.document_ai import DocumentError
from portable.api.source_detection import read_source


def row(**kwargs):
    return {
        **dict.fromkeys(document_ai.FIELDS, ""),
        "kind": "shipment",
        "jan": "4901234567894",
        "product_name": "人工商品",
        "date": "2026-10-01",
        "quantity": "2",
        "unit": "くくり",
        "location": "人工倉庫",
        "page": "1",
        **kwargs,
    }


def setup(tmp_path, monkeypatch, rows=None, complete=True):
    app = create_app(tmp_path / "Data")
    service = app.state.documents
    monkeypatch.setattr("portable.api.document_intake.ApiCredentials.load", lambda _: "synthetic")
    monkeypatch.setattr(
        "portable.api.document_intake.extract",
        lambda *_: {"rows": rows or [row()], "complete": complete},
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    result = client.post(
        "/api/documents/upload", content=b"%PDF-synthetic", headers={"x-file-name": "synthetic.pdf"}
    ).json()
    return client, service, result["id"]


def test_consent_review_conversion_and_restart(tmp_path, monkeypatch):
    client, service, identifier = setup(tmp_path, monkeypatch, [row(), row(quantity="")])
    url = f"/api/documents/{identifier}"
    assert not list(service.paths.incoming.glob("*.csv"))
    assert client.post(url + "/extract", json={}).status_code == 422
    assert client.post(url + "/extract", json={"consent": True}).status_code == 200
    assert not list(service.paths.incoming.glob("*.csv"))
    approved = {
        "confirmed": True,
        "actor": "人工確認者",
        "rows": [
            {**row(), "case_factor": "3"},
            {**row(quantity=""), "exclude": True, "reason": "判読不能"},
        ],
    }
    assert client.post(url + "/approve", json=approved).status_code == 200
    assert not list(service.paths.incoming.glob("*.csv"))
    assert client.post(url + "/dispatch", json={}).status_code == 200
    files = list(service.paths.incoming.glob("*.csv"))
    assert len(files) == 1
    contents = files[0].read_bytes()
    assert "6" in contents.decode("utf-8-sig")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(files[0].name, contents)
    with zipfile.ZipFile(buffer) as z:
        kind, center, _day, reader = read_source(z, z.infolist()[0])
        assert kind == "shipment" and center == "人工倉庫"
        assert next(iter(reader))["数量"] == "6"
    files[0].unlink()  # Simulate scanner moving accepted input.
    fresh = TestClient(create_app(service.paths.root), base_url="http://127.0.0.1")
    assert fresh.post(url + "/dispatch", json={}).status_code == 200
    assert not list(service.paths.incoming.glob("*.csv"))
    history = fresh.get("/api/documents").json()[0]
    assert history["extraction"]["rows"][0]["quantity"] == "2"
    assert history["approval"]["rows"][1]["reason"] == "判読不能"
    assert fresh.get(url + "/original").content == b"%PDF-synthetic"


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": ""},
        {"quantity": "NaN"},
        {"quantity": "-1"},
        {"case_factor": ""},
        {"case_factor": "0"},
        {"jan": "4901234567890"},
        {"date": "invalid"},
        {"unit": ""},
        {"location": ""},
    ],
)
def test_invalid_rows_never_publish(tmp_path, monkeypatch, change):
    client, service, identifier = setup(tmp_path, monkeypatch)
    service.read(identifier, True)
    r = client.post(
        f"/api/documents/{identifier}/approve",
        json={
            "confirmed": True,
            "actor": "人工",
            "rows": [{**row(), "case_factor": "1", **change}],
        },
    )
    assert r.status_code == 422
    assert service.get(identifier)["approval"] is None
    assert not list(service.paths.incoming.glob("*.csv"))


def test_incomplete_and_external_origin_and_file_type(tmp_path, monkeypatch):
    client, service, identifier = setup(tmp_path, monkeypatch, complete=False)
    service.read(identifier, True)
    assert (
        client.post(
            f"/api/documents/{identifier}/approve",
            json={"confirmed": True, "actor": "人工", "rows": [row()]},
        ).status_code
        == 422
    )
    assert client.post("/api/documents/upload", content=b"<html>bad</html>").status_code == 422
    assert (
        client.post(
            "/api/documents/upload", content=b"%PDF-test", headers={"Origin": "https://other.test"}
        ).status_code
        == 403
    )


def test_cloud_payload_and_truncation():
    def opener(request, timeout):
        payload = json.loads(request.data)
        assert payload["store"] is False
        assert payload["input"][0]["content"][1]["type"] == "input_file"
        return io.BytesIO(
            json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps({"complete": True, "rows": [row()]}),
                                }
                            ],
                        }
                    ],
                }
            ).encode()
        )

    assert (
        document_ai.extract(b"%PDF-synthetic", "fake", opener=opener)["rows"][0]["quantity"] == "2"
    )
    with pytest.raises(DocumentError):
        document_ai.extract(
            b"%PDF-test",
            "fake",
            opener=lambda *_args, **_kw: io.BytesIO(b'{"status":"incomplete","output":[]}'),
        )


def test_inventory_zero_and_exclusion_reason(tmp_path, monkeypatch):
    inventory = row(
        kind="inventory",
        quantity="0",
        expiry="2026-11-01",
        snapshot="2026-10-01",
        product_code="ARTIFICIAL",
    )
    client, service, identifier = setup(tmp_path, monkeypatch, [inventory])
    service.read(identifier, True)
    with pytest.raises(DocumentError):
        service.approve(
            identifier,
            {"actor": "test", "confirmed": True, "rows": [{**inventory, "exclude": True}]},
        )
    service.approve(
        identifier,
        {"actor": "test", "confirmed": True, "rows": [{**inventory, "case_factor": "1"}]},
    )
    service.dispatch(identifier)
    text = next(service.paths.incoming.glob("*.csv")).read_text(encoding="utf-8-sig")
    assert "明細バラ数" in text and "ARTIFICIAL" in text and ",0," in text
    original = client.get(f"/api/documents/{identifier}/original")
    assert original.headers["content-security-policy"].startswith("sandbox")


def test_image_payload_and_auth_error():
    from urllib.error import HTTPError

    def auth_error(request, timeout):
        payload = json.loads(request.data)
        source = payload["input"][0]["content"][1]
        assert source["type"] == "input_image"
        assert source["image_url"].startswith("data:image/png;base64,")
        raise HTTPError("https://api.openai.com/v1/responses", 401, "secret-test", {}, None)

    with pytest.raises(DocumentError, match="APIキーの認証") as failure:
        document_ai.extract(b"\x89PNG\r\n\x1a\nsynthetic", "not-a-real-key", opener=auth_error)
    assert "not-a-real-key" not in str(failure.value)
    assert "secret-test" not in str(failure.value)


def test_concurrent_read_only_calls_cloud_once(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    _, service, identifier = setup(tmp_path, monkeypatch)
    entered, release = Event(), Event()
    calls = []

    def slow_extract(*args):
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return {"rows": [row()], "complete": True}

    monkeypatch.setattr("portable.api.document_intake.extract", slow_extract)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.read, identifier, True)
        assert entered.wait(5)
        second = pool.submit(service.read, identifier, True)
        release.set()
        assert first.result()["extraction"] == second.result()["extraction"]
    assert len(calls) == 1


def test_modified_outgoing_csv_is_not_silently_accepted(tmp_path, monkeypatch):
    _, service, identifier = setup(tmp_path, monkeypatch)
    service.read(identifier, True)
    value = service.approve(
        identifier, {"confirmed": True, "actor": "test", "rows": [{**row(), "case_factor": "1"}]}
    )
    target = service.paths.incoming / value["approval"]["files"][0]["name"]
    target.write_bytes(b"modified by another process")
    with pytest.raises(DocumentError, match="変更されています"):
        service.dispatch(identifier)
    assert "dispatched" not in service.get(identifier)["approval"]
    assert target.read_bytes() == b"modified by another process"


def test_reviewed_document_reaches_existing_archive_analysis(tmp_path, monkeypatch):
    from datetime import date, timedelta

    rows = [row(date=str(date(2026, 9, 1) + timedelta(days=i)), case_factor='1')
            for i in range(35)]
    rows.append(row(kind='inventory', snapshot='2026-10-05', expiry='2026-11-01',
                    quantity='100', case_factor='1'))
    client, service, identifier = setup(tmp_path, monkeypatch, rows)
    service.read(identifier, True)
    service.approve(identifier, {'confirmed': True, 'actor': 'synthetic', 'rows': rows})
    service.dispatch(identifier)
    response = client.post('/api/drop-folder/scan', json={})
    assert response.status_code == 200
    receipts = response.json()['recent']
    assert len(receipts) == 1
    assert receipts[0]['status'] == 'PROCESSED', receipts
    assert receipts[0]['analysis_id']
    assert not list(service.paths.incoming.glob('*.csv'))
    assert len(list((service.paths.incoming / 'Processed').glob('*.csv'))) == 36
    assert service.get(identifier)['approval']['rows'][-1]['quantity'] == '100'


def test_pdf_saved_key_restart_and_auth_failure(tmp_path, monkeypatch):
    from portable.runtime.api_credentials import ApiCredentials

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    client = TestClient(create_app(tmp_path / "Data"), base_url="http://127.0.0.1")
    saved = client.post("/api/ai-credentials", json={"api_key": "sk-synthetic-pdf"})
    assert saved.json()["available"]
    fresh = TestClient(create_app(tmp_path / "Data"), base_url="http://127.0.0.1")
    assert fresh.get("/api/ai-credentials").json() == {"saved": True, "available": True}
    raw = b"%PDF-synthetic-persistence"
    uploaded = fresh.post("/api/documents/upload", content=raw,
                          headers={"x-file-name": "test.pdf"}).json()
    identifier = uploaded["id"]

    def fail_extract(source, key):
        assert key == "sk-synthetic-pdf" and source == raw
        raise DocumentError("APIキーの認証に失敗しました。キー設定を確認してください")

    monkeypatch.setattr("portable.api.document_intake.extract", fail_extract)
    url = f"/api/documents/{identifier}"
    failed = fresh.post(url + "/extract", json={"consent": True})
    assert failed.status_code == 422 and "認証" in failed.text
    assert "sk-synthetic-pdf" not in failed.text
    assert fresh.get(url + "/original").content == raw
    assert fresh.get("/api/documents").json()[0]["extraction"] is None
    assert ApiCredentials().status()["available"]
    monkeypatch.setattr("portable.api.document_intake.extract",
                        lambda source, key: {"rows": [row()], "complete": True})
    assert fresh.post(url + "/extract", json={"consent": True}).status_code == 200
