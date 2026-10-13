import base64
import hashlib
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from pypdf import PdfWriter

from portable.api.app import create_app
from portable.api.document_ai import FIELDS, DocumentError, extract
from portable.api.document_evidence import EVIDENCE_FIELDS, review
from portable.api.document_layout import views
from portable.api.document_suggestions import suggest_rows


def image_bytes():
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 350, 600), fill="red")
    draw.rectangle((450, 0, 800, 600), fill="blue")
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def row(**changes):
    return {
        **dict.fromkeys(FIELDS + EVIDENCE_FIELDS, ""),
        "source_region": "left",
        "product_name": "Synthetic",
        "quantity": "12",
        "source_quantity": "12",
        "quantity_status": "clear",
        "location": "甲",
        "source_location": "甲",
        "kind": "inventory",
        "source_kind": "今朝在庫",
        **changes,
    }


def value(rows=None, **changes):
    return {
        "complete": True,
        "left_complete": True,
        "right_complete": True,
        "warehouse_headers": ["甲", "神戸"],
        "rows": rows
        or [row(), row(source_region="right", location="神戸", source_location="神戸")],
        **changes,
    }


def test_physical_regions_keep_original_and_cover_both_sides():
    raw = image_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    result = views(raw)
    assert [r["name"] for r in result] == ["overview", "left", "right"]
    left = Image.open(io.BytesIO(result[1]["data"]))
    right = Image.open(io.BytesIO(result[2]["data"]))
    assert left.size == right.size == (440, 600)
    assert left.getpixel((50, 300))[0] > 240
    assert right.getpixel((390, 300))[2] > 240
    assert hashlib.sha256(raw).hexdigest() == digest


def test_pdf_renderer_and_bounds():
    writer = PdfWriter()
    writer.add_blank_page(width=800, height=600)
    output = io.BytesIO()
    writer.write(output)
    assert len(views(output.getvalue())) == 3
    writer.add_blank_page(width=800, height=600)
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(DocumentError, match="1ページ"):
        views(output.getvalue())
    with pytest.raises(DocumentError):
        views(b"not an image")


def test_label_year_location_and_quantity_are_held_without_changing_raw():
    original = row(
        jan="24TV",
        date="2023-10-06",
        source_date="10/6",
        location="甲",
        source_location="神戸",
        quantity="256",
        source_quantity="64×4",
        kind="shipment",
        source_kind="出荷リスト・今朝在庫",
    )
    result = review(value([original]), handwritten=True)
    item = result["rows"][0]
    assert item["jan"] == item["date"] == item["location"] == item["quantity"] == ""
    assert item["source_jan"] == "24TV" and item["source_ai_date"] == "2023-10-06"
    assert item["kind"] == "unknown"
    assert result["raw_rows"][0] == original
    assert original["quantity"] == "256"
    assert result["complete"] is False and result["quality_warnings"]


def test_explicit_year_is_retained_and_unknown_date_never_zeroed():
    result = review(
        value(
            [
                row(
                    date="2026-10-06",
                    source_date="2026/10/6",
                    expiry="2027-01-02",
                    source_expiry="1/2",
                ),
                row(source_region="right", location="神戸", source_location="神戸"),
            ]
        ),
        handwritten=True,
    )
    assert result["rows"][0]["date"] == "2026-10-06"
    assert result["rows"][0]["expiry"] == ""
    assert result["rows"][0]["quantity"] == "12"
    assert result["complete"] is True


def test_missing_region_warehouse_and_overlap_duplicates_require_review():
    result = review(value([row(), row()], warehouse_headers=["甲", "杉戸"]), handwritten=True)
    assert result["complete"] is False
    assert len(result["rows"]) == 2
    assert any("右表" in v for v in result["quality_warnings"])
    assert any("杉戸" in v for v in result["quality_warnings"])
    assert any("重複" in v for v in result["quality_warnings"])


def test_single_request_three_views_and_region_schema():
    calls = []

    def opener(request, **kwargs):
        body = json.loads(request.data)
        calls.append(body)
        images = [item for item in body["input"][0]["content"] if item["type"] == "input_image"]
        assert [v["detail"] for v in images] == ["low", "high", "high"]
        assert all(
            base64.b64decode(v["image_url"].split(",")[1]).startswith(b"\xff\xd8") for v in images
        )
        return io.BytesIO(
            json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": json.dumps(value())}],
                        }
                    ],
                }
            ).encode()
        )

    result = extract(image_bytes(), "synthetic-key", opener=opener, layout="two_tables")
    assert len(calls) == 1 and len(result["view_hashes"]) == 3
    assert result["layout"] == "two_tables" and result["complete"] is True


def test_suffix_completion_preserves_raw_and_refuses_conflicting_name():
    master = {
        "version": "v1",
        "products": [
            {
                "jan": "4901234567894",
                "product_name": "Synthetic",
                "product_code": "A1",
                "cell": "C2",
            }
        ],
    }
    result = suggest_rows([row(source_jan="567894")], master)[0]
    assert result["jan"] == "4901234567894" and result["source_jan"] == "567894"
    assert result["quantity"] == "12"
    master["products"].append(
        {"jan": "4901234567887", "product_name": "Other", "product_code": "A2", "cell": "C3"}
    )
    conflicting = suggest_rows([row(product_name="Other", source_jan="567894")], master)[0]
    assert conflicting["jan"] == ""


def test_layout_route_preserves_audit_and_only_fills_selected_master(tmp_path, monkeypatch):
    from portable.api import document_intake

    app = create_app(tmp_path / "Data")
    service = app.state.documents
    monkeypatch.setattr(document_intake.ApiCredentials, "load", lambda self: "synthetic-key")

    def fake(raw, key, **kwargs):
        assert kwargs["layout"] == "two_tables"
        return {
            **value(),
            "model": "gpt-6-luna",
            "layout": "two_tables",
            "view_hashes": [{"name": "left", "sha256": "test"}],
            "quality_warnings": [],
            "raw_rows": [{**r, "jan": "24TV"} for r in value()["rows"]],
        }

    monkeypatch.setattr(document_intake, "extract", fake)
    with service.db() as db:
        db.execute(
            "INSERT INTO document_masters VALUES(?,?)",
            (
                "v1",
                json.dumps(
                    {
                        "version": "v1",
                        "products": [
                            {
                                "jan": "4901234567894",
                                "product_name": "Synthetic",
                                "product_code": "A1",
                                "cell": "C2",
                            }
                        ],
                    }
                ),
            ),
        )
    client = TestClient(app, base_url="http://127.0.0.1")
    original = image_bytes()
    doc = service.add("synthetic.png", original)
    response = client.post(
        f"/api/documents/{doc['id']}/extract",
        json={"consent": True, "page": 1, "layout": "two_tables", "master_version": "v1"},
    )
    assert response.status_code == 200
    result = response.json()["extraction"]
    assert result["rows"][0]["jan"] == "4901234567894"
    assert result["model"] == "gpt-6-luna"
    assert result["raw_pages"][0]["rows"][0]["jan"] == "24TV"
    assert result["page_reviews"][0]["layout"] == "two_tables"
    assert service.get(doc["id"], original=True)[0] == original
    assert service.get(doc["id"])["approval"] is None
    response = client.post(
        f"/api/documents/{doc['id']}/extract",
        json={
            "consent": True,
            "page": 1,
            "retry": True,
            "layout": "two_tables",
            "master_version": "v1",
        },
    )
    assert response.status_code == 200
    assert service.history(doc["id"])[-1]["raw_pages"][0]["rows"][0]["jan"] == "24TV"


def test_render_failure_is_not_counted_as_an_api_call(tmp_path):
    from portable.runtime.ai_usage import AiUsage

    meter = AiUsage(tmp_path)
    with pytest.raises(DocumentError):
        meter.invoke(
            "document", lambda: extract(b"%PDF-broken", "synthetic-key", layout="two_tables")
        )
    assert meter.summary()["calls"] == 0
