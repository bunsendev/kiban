import csv
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.history_import import read_history_archive
from portable.transfers import TransferLedger, compare, shipment_class


def event(id="out", kind="TRANSFER_OUT", day="2026-10-01", quantity="100", **changes):
    return {
        "event_id": id,
        "event_date": day,
        "movement_kind": kind,
        "transfer_id": "T1",
        "line_id": "1",
        "product": "4901234567894",
        "source_location": "神戸",
        "destination_location": "杉戸",
        "quantity": quantity,
        "unit": "CASE",
        "source_file": "synthetic.csv",
        "classification_evidence": "人工伝票区分を確認",
    } | changes


def test_inventory_pair_demand_separation_trace_and_idempotence(tmp_path):
    ledger = TransferLedger(tmp_path / "ledger.db")
    rows = [
        event(),
        event("in", "TRANSFER_IN", "2026-10-02"),
        event("customer", "CUSTOMER_SHIPMENT", quantity="5"),
        event("unknown", "", quantity="7"),
    ]
    ledger.ingest(rows, "source-hash", "人工確認者")
    ledger.ingest(rows, "source-hash", "人工確認者")
    r = ledger.report("2026-10-01", "2026-10-03")
    assert r["transfer_count"] == 1
    assert {x["location"]: x["delta"] for x in r["inventory_deltas"]} == {
        "神戸": "-100",
        "杉戸": "100",
    }
    assert r["customer_shipment_rows"] == 1 and r["unresolved_count"] == 1
    assert r["movements"][0]["source_sha256"] == "source-hash"
    assert r["movements"][0]["source_row"] == 2
    early = ledger.report("2026-10-01", "2026-10-01")
    assert len(early["inventory_deltas"]) == 1
    assert early["movements"][0]["receipt_status"] == "IN_TRANSIT"
    receipt = ledger.report("2026-10-02", "2026-10-02")
    assert receipt["transfer_count"] == 0 and receipt["inventory_deltas"][0]["delta"] == "100"


def test_conflicts_atomic_no_inferred_receipt_or_pair(tmp_path):
    ledger = TransferLedger(tmp_path / "ledger.db")
    ledger.ingest([event()], "hash", "operator")
    for row in (event("in", "TRANSFER_IN", quantity="99"), event("duplicate")):
        with pytest.raises(ValueError):
            ledger.ingest([row], "other", "operator")
    assert len(ledger.rows()) == 1
    with pytest.raises(ValueError):
        ledger.ingest([event(quantity="NaN")], "hash", "operator")
    with pytest.raises(ValueError):
        ledger.ingest([event(quantity="")], "hash", "operator")
    assert shipment_class(event(classification_evidence="")) == "UNRESOLVED"
    assert shipment_class({"店名": "杉戸倉庫", "数量": "100"}) == "UNRESOLVED"


def test_reductions_units_and_missing_baseline(tmp_path):
    ledger = TransferLedger(tmp_path / "ledger.db")
    ledger.ingest(
        [event(), event("later", day="2026-10-10", quantity="60", transfer_id="T2")], "h", "op"
    )
    before = ledger.report("2026-10-01", "2026-10-05")
    after = ledger.report("2026-10-06", "2026-10-12")
    r = compare(before, after, coverage_confirmed=True)
    assert r["count_reduction_percent"] == "0"
    assert r["quantities"][0]["reduction_percent"] == "40.0"
    assert compare(before, after)["quantities"][0]["reduction_percent"] is None
    empty = ledger.report("2026-09-01", "2026-09-02")
    assert compare(empty, after, coverage_confirmed=True)["count_reduction_percent"] is None
    ledger.ingest([event("u", kind="", day="2026-10-02")], "h", "op")
    assert (
        compare(ledger.report("2026-10-01", "2026-10-05"), after, coverage_confirmed=True)[
            "count_reduction_percent"
        ]
        is None
    )


def test_history_filters_only_evidenced_transfers(tmp_path):
    rows = [
        event(),
        event("customer", "CUSTOMER_SHIPMENT", quantity="5"),
        event("unknown", "", quantity="7"),
    ]
    for row in rows:
        row.update(JAN=row["product"], 出荷日="2026-10-01", 数量=row["quantity"], 倉庫="神戸")
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("shipments.csv", text.getvalue().encode("utf-8-sig"))
    frame, provenance = read_history_archive(buffer.getvalue(), unit="CASE")
    assert frame.iloc[0]["y"] == "12"
    assert provenance["counts"]["movement_unresolved_rows"] == 1
    assert len(provenance["transfer_exclusions"]) == 1
    from portable.api.business_archive import analyze_archive

    prepared = tmp_path / "prepared.csv"
    analyze_archive(buffer.getvalue(), prepared)
    assert next(csv.DictReader(io.StringIO(prepared.read_text("utf-8"))))["y"] == "12"


def test_local_routes_template_upload_and_reduction_guard(tmp_path):
    client = TestClient(
        create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 12345)
    )
    assert client.get("/warehouse-transfers").status_code == 200
    assert client.get("/field/assets/transfers.js").status_code == 200
    assert client.get("/field/assets/transfers.css").status_code == 200
    header = client.get("/api/warehouse-transfers/template").text.lstrip("\ufeff").strip()
    body = io.StringIO()
    writer = csv.DictWriter(body, fieldnames=header.split(","))
    writer.writeheader()
    writer.writerow(event())
    r = client.post(
        "/api/warehouse-transfers",
        content=body.getvalue().encode(),
        headers={"X-Bunsen-Reviewer": "tester"},
    )
    assert r.status_code == 201
    assert (
        client.get("/api/warehouse-transfers?start=2026-10-01&end=2026-10-03").json()[
            "transfer_count"
        ]
        == 1
    )
    assert client.get("/api/warehouse-transfers?start=bad&end=bad").status_code == 422


def test_multiline_transfer_count_and_units_are_not_summed(tmp_path):
    ledger = TransferLedger(tmp_path / "ledger.db")
    ledger.ingest(
        [event(), event("other", line_id="2", product="OTHER", unit="EACH", quantity="3")],
        "h",
        "op",
    )
    result = ledger.report("2026-10-01", "2026-10-02")
    assert result["transfer_count"] == 1
    amounts = [r for r in result["aggregates"] if r["dimension"] == "product"]
    assert {(r["unit"], r["quantity"]) for r in amounts} == {("CASE", "100"), ("EACH", "3")}
    assert "total_quantity" not in result
