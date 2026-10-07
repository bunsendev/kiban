import io
import json

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pypdf import PdfWriter
from test_documents import row

from portable.api.app import create_app
from portable.api.document_ai import DocumentError
from portable.api.document_master import candidates, parse_master
from portable.api.document_pages import page_source
from portable.api.document_quantity import case_quantity


def pdf(pages=2):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pages_resume_failure_retry_and_stale_review(tmp_path, monkeypatch):
    service = create_app(tmp_path / "Data").state.documents
    identifier = service.add("artificial.pdf", pdf())["id"]
    monkeypatch.setattr("portable.api.document_intake.ApiCredentials.load", lambda _: "fake")
    calls = []

    def extract(*args, **kwargs):
        calls.append(1)
        return {"complete": True, "rows": [row()]}

    monkeypatch.setattr("portable.api.document_intake.extract", extract)
    first = service.read(identifier, True, page=1)
    assert first["extraction"]["pages_read"] == [1] and not first["extraction"]["complete"]
    assert service.read(identifier, True, page=1) == first and len(calls) == 1
    with pytest.raises(DocumentError, match="未読取"):
        service.approve(identifier, {"confirmed": True, "actor": "tester", "rows": [row()]})

    def failure(*args):
        raise DocumentError("接続失敗")

    monkeypatch.setattr("portable.api.document_intake.extract", failure)
    with pytest.raises(DocumentError):
        service.read(identifier, True, page=2)
    assert service.get(identifier)["extraction"] == first["extraction"]
    assert service.history(identifier)[-1]["status"] == "failed"
    monkeypatch.setattr("portable.api.document_intake.extract", extract)
    second = service.read(identifier, True, page=2)
    assert second["extraction"]["complete"]
    assert [r["page"] for r in second["extraction"]["rows"]] == ["1", "2"]
    with pytest.raises(DocumentError, match="更新されています"):
        service.approve(
            identifier,
            {
                "revision": first["extraction"]["revision"],
                "confirmed": True,
                "actor": "tester",
                "rows": [row(), row()],
            },
        )
    service.read(identifier, True, retry=True, page=1)
    assert len(service.get(identifier)["extraction"]["rows"]) == 2  # replace, never duplicate
    assert len(calls) == 3
    fresh = create_app(service.paths.root).state.documents
    assert len(fresh.history(identifier)) == 4
    assert len(fresh.get(identifier)["extraction"]["rows"]) == 2


def test_partial_review_manual_row_and_case_remainder_handoff(tmp_path, monkeypatch):
    app = create_app(tmp_path / "Data")
    service = app.state.documents
    identifier = service.add("artificial.pdf", pdf())["id"]
    monkeypatch.setattr("portable.api.document_intake.ApiCredentials.load", lambda _: "fake")
    source = row(
        kind="inventory",
        quantity="",
        unit="現在ケース / 現在バラ",
        snapshot="2026-10-05",
        expiry="2026-12-23",
        case_quantity="269",
        loose_quantity="2",
        units_per_case="20",
    )
    monkeypatch.setattr(
        "portable.api.document_intake.extract", lambda *_: {"complete": False, "rows": [source]}
    )
    extraction = service.read(identifier, True, page=1)["extraction"]
    approved = service.approve(
        identifier,
        {
            "revision": extraction["revision"],
            "confirmed": True,
            "actor": "tester",
            "partial_confirmed": True,
            "partial_reason": "2ページ目は別途確認、1ページの確認済み行のみ",
            "rows": [
                {**source, "component_confirmed": True},
                {**row(quantity="3"), "case_factor": "2"},
            ],
        },
    )
    assert "269.1" in approved["approval"]["files"][0]["csv"]
    assert approved["approval"]["rows"][0]["loose_quantity"] == "2"
    assert not approved["extraction"]["complete"]  # no claim of whole-document completion
    service.dispatch(identifier)
    assert len(list(service.paths.incoming.glob("*.csv"))) == 2
    with pytest.raises(DocumentError, match="確認済み"):
        service.read(identifier, True, retry=True, page=1)
    assert service.get(identifier)["approval"] == service.approve(identifier, {})["approval"]
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get(f"/api/documents/{identifier}/history").status_code == 200


@pytest.mark.parametrize(
    "change",
    [
        {"component_confirmed": False},
        {"loose_quantity": ""},
        {"case_quantity": ""},
        {"units_per_case": ""},
        {"units_per_case": "0"},
        {"loose_quantity": "NaN"},
        {"units_per_case": "3", "loose_quantity": "1"},
    ],
)
def test_component_quantity_requires_explicit_finite_conversion(change):
    source = {
        "case_quantity": "269",
        "loose_quantity": "2",
        "units_per_case": "20",
        "component_confirmed": True,
    }
    with pytest.raises(DocumentError):
        case_quantity(source | change)
    assert str(case_quantity(source | {"loose_quantity": "0", "units_per_case": ""})) == "269"


def master_bytes():
    book = Workbook()
    tab = book.active
    tab.title = "current"
    tab.append(["商品名", "商品コード", "JANコード", "商品名", "商品コード", "JANコード"])
    tab.append(["人工品", "A", "4901234567894", "人工品増量", "B", "4901234567894"])
    tab.append(["bad", "C", "=1+1", None, None, None])
    old = book.create_sheet("old")
    old.append(["商品名", "商品コード", "JANコード"])
    old.append(["旧商品", "A", "4901234567887"])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def test_master_versions_duplicate_jan_formula_and_selection(tmp_path):
    raw = master_bytes()
    current = parse_master(raw, "current", "2026-10-01")
    old = parse_master(raw, "old", "2025-01-01")
    assert len(current["products"]) == 2 and current["invalid_rows"] == 1
    assert len(candidates(current, {"jan": "4901234567894"})) == 2
    assert candidates(current, {"product_code": "A"})[0]["jan"] != old["products"][0]["jan"]
    assert current["version"] != old["version"]
    client = TestClient(create_app(tmp_path / "Data"), base_url="http://127.0.0.1")
    assert client.post("/api/document-master", content=raw).json()["sheets"] == ["current", "old"]
    value = client.post(
        "/api/document-master",
        content=raw,
        headers={"x-master-sheet": "current", "x-effective-date": "2026-10-01"},
    )
    assert value.status_code == 200 and value.json()["count"] == 2
    result = client.post(
        "/api/document-master/candidates",
        json={"version": current["version"], "row": {"product_code": "A"}},
    )
    assert len(result.json()["candidates"]) == 1
    assert client.post("/api/document-master", content=b"not a workbook").status_code == 422


def test_pdf_page_boundary_and_no_embedded_text_for_blank():
    raw = pdf()
    part, text, count = page_source(raw, 2)
    assert part.startswith(b"%PDF-") and not text and count == 2
    for invalid in (0, 3, True, "1"):
        with pytest.raises(DocumentError):
            page_source(raw, invalid)


def test_printed_table_current_columns_no_subtotal_or_missing_zero(monkeypatch):
    from portable.api import document_inventory_pdf as adapter

    header = " " * 60 + "ケース バラ " * 5
    c, b = header.rfind("ケース"), header.rfind("バラ")
    line = "4901234567894 人工品 20 26/12/23".ljust(c) + "269".ljust(b - c) + "2"
    text = "在庫集計日：2026/10/05 現在\n" + header + "\n" + line + "\n商品合計 999"
    monkeypatch.setattr(adapter, "page_source", lambda *_: (b"", text, 1))
    result = adapter.extract_inventory(pdf(1))
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["case_quantity"] == "269" and row["loose_quantity"] == "2"
    assert row["quantity"] == "" and row["units_per_case"] == "20"
    assert row["snapshot"] == "2026-10-05" and row["expiry"] == "2026-12-23"
    monkeypatch.setattr(adapter, "page_source", lambda *_: (b"", "", 1))
    with pytest.raises(DocumentError, match="AI読取"):
        adapter.extract_inventory(pdf(1))


def test_local_read_keeps_other_pages_when_cloud_retry(tmp_path, monkeypatch):
    service = create_app(tmp_path / "Data").state.documents
    identifier = service.add("synthetic.pdf", pdf())["id"]
    monkeypatch.setattr(
        "portable.api.document_intake.extract_inventory",
        lambda *_: {
            "rows": [row(page="1"), row(page="2")],
            "complete": True,
            "pages_read": [1, 2],
            "page_count": 2,
            "model": "printed-inventory-v1",
        },
    )
    local = service.read_local(identifier)
    monkeypatch.setattr("portable.api.document_intake.ApiCredentials.load", lambda _: "fake")
    monkeypatch.setattr(
        "portable.api.document_intake.extract",
        lambda *_: {"complete": True, "rows": [row(quantity="9")]},
    )
    after = service.read(identifier, True, retry=True, page=1)
    assert [r["quantity"] for r in after["extraction"]["rows"]] == ["9", "2"]
    assert service.history(identifier)[0]["revision"] == local["extraction"]["revision"]
    assert json.dumps(service.history(identifier)).count("fake") == 0
