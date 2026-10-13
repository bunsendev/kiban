import io

from openpyxl import Workbook

from portable.api.document_master import candidates, parse_master
from portable.api.document_suggestions import suggest_rows


def master():
    return {
        "version": "synthetic-v1",
        "products": [
            {
                "jan": "4901234567894",
                "product_code": "A",
                "product_name": "人工商品75g",
                "cell": "C2",
            }
        ],
    }


def test_new_master_layout_keeps_name_and_product_code():
    wb = Workbook()
    ws = wb.active
    ws.append(["商品名", None, "JANコード", "商品コード 1070400"])
    ws.append(["24TV", "人工商品75g", "4901234567894", "A"])
    data = io.BytesIO()
    wb.save(data)
    value = parse_master(data.getvalue(), ws.title, "2026-10-13")
    assert value["products"][0]["product_name"] == "人工商品75g"
    assert value["products"][0]["product_code"] == "A"


def test_local_suggestion_never_infers_quantity_dates_or_approval():
    source = {
        "jan": "24TV",
        "product_name": "人工商品７５ｇ",
        "quantity": "",
        "date": "",
        "component_confirmed": False,
    }
    result = suggest_rows([source], master())[0]
    assert result["jan"] == "4901234567894" and result["source_jan"] == "24TV"
    assert result["quantity"] == "" and result["date"] == ""
    assert result["component_confirmed"] is False and source["jan"] == "24TV"


def test_ambiguous_variant_and_existing_jan_remain_unchanged():
    value = master()
    value["products"].append({**value["products"][0], "product_code": "B"})
    assert suggest_rows([{"product_name": "人工商品75g", "jan": ""}], value)[0]["jan"] == ""
    assert suggest_rows([{"product_name": "人工商品75g", "jan": "4901234567894"}], value)[0] == {
        "product_name": "人工商品75g",
        "jan": "4901234567894",
    }


def test_reviewed_name_alias_is_bound_to_selected_master_version():
    row = {"jan": "", "product_name": "人工読み違い"}
    approved = [
        {**row, "jan": "4901234567894", "product_code": "A", "master_version": "synthetic-v1"}
    ]
    assert suggest_rows([row], master(), approved)[0]["jan"] == "4901234567894"
    approved[0]["master_version"] = "different-version"
    assert suggest_rows([row], master(), approved)[0]["jan"] == ""


def test_fuzzy_candidate_is_only_a_suggestion_and_preserves_pack_size():
    value = {
        "version": "v",
        "products": [
            {
                "jan": "4901234567894",
                "product_code": "A",
                "product_name": "7種具材の卯の花75g",
                "cell": "C2",
            }
        ],
    }
    row = {"product_name": "7種具材の別の花75g", "jan": ""}
    assert candidates(value, row)[0]["match_basis"] == "商品名類似（原本確認）"
    assert suggest_rows([row], value)[0]["jan"] == ""
    assert candidates(value, {"product_name": "7種具材の別の花140g"}) == []


def test_batch_endpoint_uses_selected_master_without_ai_or_publication(tmp_path):
    import json

    from fastapi.testclient import TestClient

    from portable.api.app import create_app

    app = create_app(tmp_path / "Data")
    client = TestClient(app, base_url="http://127.0.0.1")
    with app.state.documents.db() as db:
        db.execute(
            "INSERT INTO document_masters VALUES(?,?)", (master()["version"], json.dumps(master()))
        )
    response = client.post(
        "/api/document-master/suggest-rows",
        json={"version": "synthetic-v1", "rows": [{"jan": "24TV", "product_name": "人工商品75g"}]},
    )
    assert response.status_code == 200
    assert response.json()["rows"][0]["jan"] == "4901234567894"
    assert not list(app.state.documents.paths.incoming.glob("*.csv"))
    assert (
        client.post(
            "/api/document-master/suggest-rows", json={"version": "unknown", "rows": []}
        ).status_code
        == 422
    )
