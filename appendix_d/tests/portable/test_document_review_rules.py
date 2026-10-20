import hashlib
import io
import json
import sqlite3
import uuid
import zipfile
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_document_movement import movement_text
from test_document_review import pdf

from portable.api import document_intake
from portable.api import document_inventory_pdf as native_adapter
from portable.api.app import create_app
from portable.api.document_ai import DocumentError
from portable.api.document_review_plan import TEMPLATE, classify
from portable.api.input_history import InputHistory


def extraction(warehouse="人工倉庫", day="2026-10-13"):
    rows = [
        {
            "kind": "inventory",
            "jan": "4901234567894",
            "product_code": "A1",
            "product_name": "人工品",
            "location": warehouse,
            "snapshot": day,
            "date": "",
            "expiry": "2027-01-01",
            "source_detail_date": "2026-10-01",
            "page": "1",
            "quantity": "",
            "unit": "現在ケース / 現在バラ",
            "case_quantity": "5",
            "loose_quantity": "2",
            "units_per_case": "10",
        }
    ]
    rows.append(
        {
            **rows[0],
            "jan": "4006381333931",
            "product_code": "A2",
            "case_quantity": "1",
            "loose_quantity": "0",
            "units_per_case": "20",
        }
    )
    return {
        "model": TEMPLATE,
        "rows": rows,
        "complete": True,
        "pages_read": [1],
        "page_count": 1,
        "coverage": {"matched": True},
        "inventory_checks": {
            "movement_rows": [{"status": "match", "page": "1"} for _ in rows],
            "repeated_buckets": [],
        },
    }


def document(service, monkeypatch, **kwargs):
    raw = pdf(1) + b"\n%" + uuid.uuid4().hex.encode()
    doc = service.add("synthetic.pdf", raw)
    value = extraction(**kwargs)
    monkeypatch.setattr(document_intake, "extract_inventory", lambda *_a, **_k: deepcopy(value))
    return service.read_local(doc["id"])


def prepare(service, doc, **overrides):
    value = {
        "rows": doc["extraction"]["rows"],
        "revision": doc["extraction"]["revision"],
        "actor": "人工確認者",
        "reason": "単位定義を原本で確認",
        "effective_date": "2026-10-13",
        "remember": True,
    }
    value.update(overrides)
    return service.review.preview(doc["id"], value)


def apply(service, doc, preview, **overrides):
    value = {"preview_id": preview["id"], "rows": doc["extraction"]["rows"], "confirmed": True}
    value.update(overrides)
    return service.review.apply(doc["id"], value)


def test_preview_apply_reuse_preserves_original_and_never_approves(tmp_path, monkeypatch):
    service = create_app(tmp_path).state.documents
    doc = document(service, monkeypatch)
    original = deepcopy(doc["extraction"])
    plan = service.review.plan(doc["id"])
    assert plan["counts"] == {"READY": 2}
    preview = prepare(service, doc)
    assert preview["target_count"] == 2
    assert service.get(doc["id"])["draft"] is None
    applied = apply(service, doc, preview)
    assert applied["formal_approval"] is False
    saved = service.get(doc["id"])
    assert saved["extraction"] == original and saved["approval"] is None
    assert [r["units_per_case"] for r in saved["draft"]["rows"]] == ["10", "20"]
    assert service.review.plan(doc["id"])["counts"] == {"READY": 2}
    next_doc = document(service, monkeypatch, day="2026-10-14")
    assert service.review.plan(next_doc["id"])["counts"] == {"READY": 2}
    assert service.get(next_doc["id"])["draft"] is None
    manual_rows = deepcopy(service.review.plan(next_doc["id"])["rows"])
    manual_rows[0].update(component_confirmed=False, component_rule_override="manual")
    service.save_draft(
        next_doc["id"], {"rows": manual_rows, "revision": next_doc["extraction"]["revision"]}
    )
    manual_plan = service.review.plan(next_doc["id"])
    assert manual_plan["rows"][0]["component_confirmed"] is False
    assert manual_plan["classifications"][0]["status"] == "REVIEW"
    with service.db() as db:
        assert db.execute("SELECT COUNT(*) FROM document_rule_uses").fetchone()[0] == 3


@pytest.mark.parametrize("change", ["warehouse", "date", "template", "master"])
def test_rule_is_not_reused_outside_scope(tmp_path, monkeypatch, change):
    service = create_app(tmp_path).state.documents
    doc = document(service, monkeypatch)
    apply(service, doc, prepare(service, doc))
    kwargs = {"warehouse": "別倉庫"} if change == "warehouse" else {}
    if change == "date":
        kwargs["day"] = "2026-10-12"
    other = document(service, monkeypatch, **kwargs)
    if change == "template":
        with service.db() as db:
            value = other["extraction"]
            value["model"] = "synthetic-ai"
            db.execute(
                "UPDATE documents SET extraction=? WHERE id=?", (json.dumps(value), other["id"])
            )
    plan = service.review.plan(
        other["id"], master_version="another-version" if change == "master" else ""
    )
    assert plan["applied_rules"] == {}
    assert all(not r.get("component_rule_version") for r in plan["rows"])
    assert all(r.get("component_confirmed", False) is (change != "template") for r in plan["rows"])


@pytest.mark.parametrize("change", ["edit", "draft", "cancel", "rule"])
def test_stale_preview_is_rejected(tmp_path, monkeypatch, change):
    service = create_app(tmp_path).state.documents
    doc = document(service, monkeypatch)
    preview = prepare(service, doc)
    rows = deepcopy(doc["extraction"]["rows"])
    if change == "edit":
        rows[0]["case_quantity"] = "99"
    elif change == "draft":
        service.save_draft(doc["id"], {"rows": rows, "revision": doc["extraction"]["revision"]})
    elif change == "cancel":
        service.set_cancelled(doc["id"])
    else:
        other = document(service, monkeypatch)
        apply(service, other, prepare(service, other))
    with pytest.raises(DocumentError):
        apply(service, doc, preview, rows=rows)


def test_disable_is_audited_and_does_not_restore_older_rule(tmp_path, monkeypatch):
    service = create_app(tmp_path).state.documents
    for _ in range(2):
        doc = document(service, monkeypatch)
        apply(service, doc, prepare(service, doc))
    rules = service.review.rules()
    assert len(rules) == 2 and rules[-1]["current"]
    service.review.disable(rules[-1]["version"], {"actor": "人工", "reason": "運用変更"})
    other = document(service, monkeypatch)
    assert service.review.plan(other["id"])["applied_rules"] == {}
    assert service.get(doc["id"])["approval"] is None


def test_complete_flag_does_not_hide_missing_structure_quantity_or_ai(tmp_path):
    source = extraction()
    rows = [{**r, "component_confirmed": True} for r in source["rows"]]
    assert all(s["status"] == "READY" for s in classify(source, rows))
    source["coverage"]["matched"] = False
    assert all(s["status"] == "REVIEW" for s in classify(source, rows))
    source["coverage"]["matched"] = True
    rows[0]["loose_quantity"] = ""
    assert classify(source, rows)[0]["status"] == "HOLD"
    rows[0]["loose_quantity"] = "0"
    source["model"] = "synthetic-ai"
    assert classify(source, rows)[1]["status"] == "REVIEW"
    source["complete"] = False
    assert all(s["status"] == "HOLD" for s in classify(source, rows))


def test_http_preview_page_and_guarded_approval(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    service = app.state.documents
    doc = document(service, monkeypatch)
    client = TestClient(app, base_url="http://127.0.0.1")
    url = f"/api/documents/{doc['id']}"
    assert client.get(url + "/page/1").headers["content-type"] == "image/jpeg"
    assert client.get(url + "/page/999").status_code == 422
    plan = client.post(url + "/review/plan", json={})
    assert plan.status_code == 200 and plan.json()["native"]
    preview = prepare(service, doc)
    assert (
        client.post(
            url + "/review/apply",
            json={"preview_id": preview["id"], "rows": doc["extraction"]["rows"]},
        ).status_code
        == 422
    )
    apply(service, doc, preview)
    saved = service.get(doc["id"])
    rows = saved["draft"]["rows"]
    rows[0]["expiry"] = ""
    bad = client.post(
        url + "/approve",
        json={
            "rows": rows,
            "actor": "人工",
            "confirmed": True,
            "revision": saved["extraction"]["revision"],
            "review_guard": True,
        },
    )
    assert bad.status_code == 422 and "保留" in bad.json()["detail"]
    assert service.get(doc["id"])["approval"] is None


def test_history_key_upgrade_retains_identical_inventory_on_different_dates(tmp_path):
    app = create_app(tmp_path)
    paths = app.state.documents.paths
    raw = b"product-data"
    path = paths.state / "input-history.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM history_meta")
        old = hashlib.sha256(raw).hexdigest()
        db.execute(
            "INSERT INTO files VALUES(?,?,?,?,?,?,?,?)",
            (
                old,
                "legacy.csv",
                "inventory",
                "人工倉庫",
                '["2026-10-12"]',
                "synthetic",
                raw,
                "original-archive",
            ),
        )
    history = InputHistory(paths)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT raw FROM files").fetchone()[0] == raw
        assert db.execute("SELECT COUNT(*) FROM history_key_migrations").fetchone()[0] == 1
        db.execute("DELETE FROM files")
    for day in ("20261012", "20261013"):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr(
                f"人工倉庫日時在庫_{day}.csv",
                "商品コード,賞味期限,明細バラ数\n4901234567894,20270101,10\n".encode(),
            )
        with history.stage(out.getvalue()) as (_, meta):
            assert meta["new_files"] == 1
    assert meta["candidate_files"] == 2


def test_native_complete_detects_unparsed_product_anchor(monkeypatch):
    text = movement_text()
    text += "\n" + text.splitlines()[-1].replace("4901234567894", "567894       ", 1)
    monkeypatch.setattr(native_adapter, "page_source", lambda *_: (b"", text, 1))
    value = native_adapter.extract_inventory(pdf(1))
    assert value["complete"] is False
    assert value["coverage"]["pages"][0]["candidate_rows"] == 2
    assert value["coverage"]["pages"][0]["recognized_rows"] == 1
    assert value["coverage"]["matched"] is False


def test_edited_warehouse_cannot_be_used_to_create_unit_rule(tmp_path, monkeypatch):
    service = create_app(tmp_path).state.documents
    doc = document(service, monkeypatch)
    rows = deepcopy(doc["extraction"]["rows"])
    for row in rows:
        row["location"] = "原本と異なる倉庫"
    with pytest.raises(DocumentError, match="原本と異なる"):
        prepare(service, doc, rows=rows)


def test_partial_guard_keeps_source_incomplete_and_blocks_bad_values(tmp_path, monkeypatch):
    service = create_app(tmp_path).state.documents
    doc = document(service, monkeypatch)
    source = doc["extraction"]
    source["complete"] = False
    with service.db() as db:
        db.execute("UPDATE documents SET extraction=? WHERE id=?", (json.dumps(source), doc["id"]))
    rows = [{**r, "component_confirmed": True} for r in source["rows"]]
    saved = service.approve(
        doc["id"],
        {
            "actor": "人工",
            "confirmed": True,
            "rows": rows,
            "revision": source["revision"],
            "review_guard": True,
            "partial_confirmed": True,
            "partial_reason": "原本で取得範囲だけ確認",
        },
    )
    assert saved["extraction"]["complete"] is False
    assert saved["approval"]["partial_confirmed"] is True
    assert not saved["approval"].get("dispatched")


def test_empty_daily_csvs_on_different_days_are_distinct(tmp_path):
    service = create_app(tmp_path).state.documents
    history = InputHistory(service.paths)
    for day_value in ("20261012", "20261013"):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr(f"人工倉庫日時出荷_{day_value}.csv", "出荷日,JAN,数量\n".encode())
        with history.stage(out.getvalue()) as (_, meta):
            assert meta["new_files"] == 1
    assert meta["candidate_files"] == 2


def test_rebuild_reads_original_archives_not_only_old_combined_inputs(tmp_path):
    app = create_app(tmp_path)
    db_path = app.state.documents.paths.state / "input-history.sqlite3"
    for day_value in ("20261012", "20261013"):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr(
                f"人工倉庫日時在庫_{day_value}.csv",
                "商品コード,賞味期限,明細バラ数\n4901234567894,20270101,10\n".encode(),
            )
        raw = out.getvalue()
        with sqlite3.connect(db_path) as db:
            db.execute("INSERT INTO archives VALUES(?,?)", (hashlib.sha256(raw).hexdigest(), raw))
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post("/api/field/input-history/rebuild")
    assert response.status_code == 200 and not response.json()["errors"]
    assert len(response.json()["accepted"]) == 2
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 2
    assert not app.state.documents.list()


def test_builtin_definition_removes_repeat_questions_but_keeps_blank_and_factor_guards(
    tmp_path, monkeypatch
):
    service = create_app(tmp_path).state.documents
    doc = document(service, monkeypatch)
    original = deepcopy(doc["extraction"])
    plan = service.review.plan(doc["id"])
    assert all(
        r["component_definition_version"] == "bunsen-ball-case-each-v1" for r in plan["rows"]
    )
    assert all("意味が未確認" not in c for item in plan["classifications"] for c in item["causes"])
    from portable.api.document_quantity import case_quantity

    assert str(case_quantity(plan["rows"][0])) == "5.2"
    for change in ({"loose_quantity": ""}, {"units_per_case": ""}, {"case_quantity": "-1"}):
        rows = deepcopy(plan["rows"])
        rows[0].update(change)
        assert service.review.plan(doc["id"], rows=rows)["classifications"][0]["status"] == "HOLD"
    assert service.get(doc["id"])["extraction"] == original
    assert service.get(doc["id"])["approval"] is None


def test_builtin_definition_does_not_accept_changed_source_columns(tmp_path, monkeypatch):
    service = create_app(tmp_path).state.documents
    doc = document(service, monkeypatch)
    rows = service.review.plan(doc["id"])["rows"]
    rows[0]["unit"] = "パレット / バラ"
    plan = service.review.plan(doc["id"], rows=rows)
    assert plan["rows"][0]["component_confirmed"] is False
    assert "component_definition_version" not in plan["rows"][0]
    assert "原本の数量列の対応を確認" in plan["classifications"][0]["causes"]
