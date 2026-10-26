"""A saved blank policy reaches bulk extraction without adopting any document."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from test_document_review import pdf

from portable.api import document_inventory_pdf as adapter
from portable.api.app import create_app
from portable.api.document_ai import DocumentError


def original(service, *, day="2026-10-14", warehouse="人工倉庫"):
    raw = pdf(1) + b"\n%TEST " + json.dumps(
        {"day": day, "warehouse": warehouse, "id": uuid.uuid4().hex}, ensure_ascii=False
    ).encode()
    return service.add("artificial.pdf", raw)["id"]


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTABLE_SMOKE", "1")

    def source(raw, _number):
        settings = json.loads(raw.split(b"%TEST ")[-1])
        lines = [f"在庫集計日：{settings['day'].replace('-', '/')} 現在 当出",
                 "㈱ムロオ " + settings["warehouse"], " " * 60 + "ケース バラ " * 5]
        for jan, before, out, current in [
            ("4901234567894", "5", "1", "4"), ("4006381333931", "2", "2", "")
        ]:
            line = f"{jan} 人工品 20 27/01/01".ljust(60)
            line += "".join(a.ljust(4) + b.ljust(3) for a, b in [
                (before, ""), ("", ""), (out, ""), ("", ""), (current, "")
            ])
            lines.extend([line, " (2026/10/01)"])
        return b"", "\n".join(lines), 1

    monkeypatch.setattr(adapter, "page_source", source)
    return create_app(tmp_path / "Data").state.documents


def save_rule(service, *, blanks=True, master=""):
    identifier = original(service, day="2026-10-13")
    doc = service.read_local(identifier, blank_current_zero=True)
    data = {"rows": doc["extraction"]["rows"], "revision": doc["extraction"]["revision"],
            "actor": "人工確認者", "reason": "原本の現在欄の空欄は0と確認",
            "effective_date": "2026-10-13", "remember": True,
            "blank_current_zero": blanks, "master_version": master}
    preview = service.review.preview(identifier, data)
    result = service.review.apply(identifier, {
        "preview_id": preview["id"], "rows": data["rows"], "confirmed": True,
    })
    return identifier, result["rule_version"]


def test_saved_rule_reaches_bulk_http_read_and_survives_restart(service):
    first, version = save_rule(service)
    before = service.get(first)["extraction"]
    second = original(service)
    app = create_app(service.paths.root)
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post(f"/api/documents/{second}/local", json={"reuse_blank_rule": True})
    assert response.status_code == 200
    doc = response.json()
    assert doc["extraction"]["blank_rule_versions"] == [version]
    a, out_a, b, out_b = doc["extraction"]["rows"]
    assert (a["case_quantity"], a["loose_quantity"], a["source_current_loose"]) == ("4", "0", "")
    assert b["exclude"] and b["case_quantity"] == b["loose_quantity"] == "0"
    assert (out_a["case_quantity"], out_b["case_quantity"]) == ("1", "2")
    assert not out_a["exclude"] and not out_b["exclude"]
    assert doc["approval"] is None and doc["draft"] is None
    assert app.state.documents.review.plan(second)["counts"] == {"READY": 3, "EXCLUDED": 1}
    assert service.get(first)["extraction"] == before
    assert service.get(first)["approval"] is None


@pytest.mark.parametrize("change", ["missing", "legacy", "warehouse", "date", "master",
                                   "disabled", "replaced", "template"])
def test_bulk_blanks_remain_unknown_outside_saved_scope(service, monkeypatch, change):
    if change != "missing":
        _, version = save_rule(service, blanks=change != "legacy")
    kwargs = {"reuse_blank_rule": True}
    source_kwargs = {}
    if change == "warehouse":
        source_kwargs["warehouse"] = "別の人工倉庫"
    if change == "date":
        source_kwargs["day"] = "2026-10-12"
    if change == "master":
        with service.db() as db:
            db.execute("INSERT INTO document_masters VALUES(?,?)", ("other", "{}"))
        kwargs["master_version"] = "other"
    if change == "disabled":
        service.review.disable(version, {"actor": "人工", "reason": "適用中止"})
    if change == "replaced":
        save_rule(service, blanks=False)
    if change == "template":
        native = adapter.extract_inventory

        def changed(*args, **kw):
            return {**native(*args, **kw), "model": "new-template"}

        monkeypatch.setattr("portable.api.document_intake.extract_inventory", changed)
    doc = service.read_local(original(service, **source_kwargs), **kwargs)
    assert doc["extraction"]["blank_rule_versions"] == []
    a, _, b, _ = doc["extraction"]["rows"]
    assert a["loose_quantity"] == "" and b["case_quantity"] == ""
    assert not b.get("exclude") and doc["approval"] is None


def test_master_scope_and_rule_revocation_block_even_partial_approval(service):
    with service.db() as db:
        db.execute("INSERT INTO document_masters VALUES(?,?)", ("master-a", "{}"))
    _, version = save_rule(service, master="master-a")
    identifier = original(service)
    doc = service.read_local(identifier, reuse_blank_rule=True, master_version="master-a")
    assert doc["extraction"]["blank_rule_versions"] == [version]
    payload = {"rows": doc["extraction"]["rows"], "revision": doc["extraction"]["revision"],
               "actor": "人工", "confirmed": True, "review_guard": True,
               "partial_confirmed": True, "partial_reason": "一部採用"}
    with pytest.raises(DocumentError, match="空欄ルール"):
        service.approve(identifier, payload)
    service.review.disable(version, {"actor": "人工", "reason": "失効"})
    plan = service.review.plan(identifier, master_version="master-a")
    assert plan["blank_rule_error"] and plan["counts"]["HOLD"] == 2
    with pytest.raises(DocumentError, match="空欄ルール"):
        service.approve(identifier, {**payload, "master_version": "master-a"})
    assert service.get(identifier)["approval"] is None
    assert service.get(identifier)["extraction"] == doc["extraction"]


def test_cannot_save_zero_rule_without_explicit_source_policy(service):
    identifier = original(service)
    doc = service.read_local(identifier)
    payload = {"rows": doc["extraction"]["rows"], "revision": doc["extraction"]["revision"],
               "actor": "人工", "reason": "人工確認", "effective_date": "2026-10-13",
               "remember": True, "blank_current_zero": True}
    with pytest.raises(DocumentError, match="読み直し"):
        service.review.preview(identifier, payload)
    assert not service.review.rules()


def test_local_rule_request_rejects_invalid_flags_and_missing_master(service):
    app = create_app(service.paths.root)
    client = TestClient(app, base_url="http://127.0.0.1")
    identifier = original(service)
    for value in [
        {"reuse_blank_rule": "true"}, {"reuse_blank_rule": True, "master_version": []},
        {"reuse_blank_rule": True, "blank_current_zero": True},
        {"reuse_blank_rule": True, "master_version": "not-registered"},
    ]:
        assert client.post(f"/api/documents/{identifier}/local", json=value).status_code == 422
    assert service.get(identifier)["extraction"] is None
