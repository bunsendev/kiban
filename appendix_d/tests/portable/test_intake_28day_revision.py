import csv
import io
import json
import zipfile
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from test_document_movement import movement_text

from portable.api import document_inventory_pdf as adapter
from portable.api.app import create_app
from portable.api.business_archive import ArchiveError, analyze_archive
from portable.api.business_archive_intake import BusinessArchiveIntake
from portable.api.formal_shipment_daily import build_daily_shipment
from portable.api.inventory_handoff import inventory_centers
from portable.api.reference_demand import demand_forecast

JAN = "4901234567894"
END = date(2026, 10, 13)


def bundle(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, raw in files.items():
            z.writestr(name, raw)
    return out.getvalue()


def shipment(day, quantity="2"):
    return (
        f"倉庫,基準日,出荷日,JAN,商品名,数量\n人工倉庫,{day},{day},{JAN},TV人工品,{quantity}\n"
    ).encode("utf-8-sig")


def stock(day, header="在庫数"):
    return (
        f"JAN,倉庫,基準日時,賞味期限,{header}\n{JAN},人工倉庫,{day}T16:00:00+09:00,2027-01-01,10\n"
    ).encode()


def test_duplicate_csvs_inside_first_zip_are_not_counted_twice(tmp_path):
    app = create_app(tmp_path / "Data")
    paths = app.state.documents.paths

    class Daily:
        def view(self, *_):
            return {}

    service = BusinessArchiveIntake(paths, Daily())
    report = service.ingest(bundle({"a.csv": shipment(END), "renamed.csv": shipment(END)}))
    assert report["files"]["shipment"] == 1
    assert report["rows"]["shipment"] == 1
    assert report["input_history"]["duplicate_files"] == 1


def test_identical_legacy_bytes_in_different_warehouses_are_retained(tmp_path):
    app = create_app(tmp_path / "Data")
    paths = app.state.documents.paths

    class Daily:
        def view(self, *_):
            return {}

    service = BusinessArchiveIntake(paths, Daily())
    raw = f"出荷日,JAN,数量\n{END},{JAN},2\n".encode()
    report = service.ingest(bundle({
        "人工甲日時出荷_20261013.csv": raw,
        "人工乙日時出荷_20261013.csv": raw,
    }))
    assert report["files"]["shipment"] == 2
    assert report["rows"]["shipment"] == 2
    report = service.ingest(bundle({"人工甲日時出荷_20261013.csv": raw}))
    assert report["files"]["shipment"] == 1
    assert report["input_history"]["duplicate_files"] == 1


def test_csv_aliases_delimiters_and_explicit_inventory_date(tmp_path):
    raw = bundle({"任意A.csv": shipment(END), "名前無関係.csv": stock(END).replace(b",", b"\t")})
    report = analyze_archive(raw, tmp_path / "prepared.csv")
    assert report["files"]["inventory"] == report["files"]["shipment"] == 1
    assert report["products"]["inventory_codes_matched_to_shipment_jan"] == 1
    path = tmp_path / "input.zip"
    path.write_bytes(raw)
    assert inventory_centers(path) == [{"source_center": "人工倉庫", "latest_date": "2026-10-13"}]
    assert report["source_files"][1]["kind"] == "inventory"


def test_wrong_inventory_shape_and_date_mismatch_name_are_visible(tmp_path):
    raw = bundle({"shipment.csv": shipment(END), "bad.csv": b"JAN,price\n4901234567894,2\n"})
    report = analyze_archive(raw, tmp_path / "prepared.csv")
    assert report["files"]["inventory"] == 0
    assert report["issues"][0]["source_value"] == "bad.csv"
    with pytest.raises(ArchiveError, match="出荷日とファイル"):
        analyze_archive(bundle({"神戸日時出荷_20261012.csv": shipment(END)}), tmp_path / "p.csv")


def test_individual_history_equals_batch_and_duplicate_no_growth(tmp_path):
    app = create_app(tmp_path / "individual")
    paths = app.state.documents.paths

    class Daily:
        def view(self, *_):
            return {}

    service = BusinessArchiveIntake(paths, Daily())
    days = [END - timedelta(days=i) for i in reversed(range(28))]
    for day in days:
        final = service.ingest(bundle({f"{day}.csv": shipment(day)}))
    prepared = paths.prepared / f"{final['analysis_id']}.csv"
    assert len(list(csv.DictReader(prepared.open(encoding="utf-8")))) == 28
    assert final["input_history"]["candidate_files"] == 28
    repeated = service.ingest(bundle({"renamed.csv": shipment(END)}))
    assert repeated["input_history"]["candidate_files"] == 28
    assert repeated["input_history"]["duplicate_files"] == 1
    with pytest.raises(ArchiveError, match="異なるCSV"):
        service.ingest(bundle({"revision.csv": shipment(END, "999")}))
    batch = analyze_archive(
        bundle({f"{day}.csv": shipment(day) for day in days}), tmp_path / "batch.csv"
    )
    assert batch["prepared_rows"] == 28
    assert prepared.read_bytes() == (tmp_path / "batch.csv").read_bytes()
    demand = demand_forecast(
        paths, final["analysis_id"], {"actor": "人工", "unit": "ボール", "confirmed": True}
    )
    assert demand["series"][0]["required_start"] == "2026-09-16"
    assert demand["series"][0]["recognized_days"] == 28
    assert len(demand["predictions"]) == 14
    assert demand["inventory"] is None and not demand["inventory_risk_evaluated"]


def test_formal_latest28_gap_not_hidden_by_old_history(tmp_path):
    days = [END - timedelta(days=i) for i in reversed(range(40)) if i != 10]
    raw = bundle({f"{day}.csv": shipment(day) for day in days})
    source = tmp_path / "input.zip"
    source.write_bytes(raw)
    prepared = tmp_path / "prepared.csv"
    analyze_archive(raw, prepared)
    import hashlib

    build, _ = build_daily_shipment(
        archive_path=source,
        prepared_path=prepared,
        handoff={"source_archive_sha256": hashlib.sha256(raw).hexdigest()},
        registration_id="synthetic",
        identities=[
            {
                "source_center": "人工倉庫",
                "jan": JAN,
                "canonical_product_id": "p",
                "forecast_center_id": "c",
            }
        ],
        zero_when_file_present=True,
    )
    row = build["series"][0]
    assert row["observed_day_count"] == 39
    assert row["recognized_required_days"] == 27
    assert row["missing_required_dates"] == ["2026-10-03"]
    assert not row["forecast_eligible"]


def document(day):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/SyntheticDay": str(day)})
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def report_text(raw):
    from pypdf import PdfReader

    day = PdfReader(io.BytesIO(raw)).metadata["/SyntheticDay"]
    text = movement_text().replace("2026/10/05", day.replace("-", "/"))
    text = text.rsplit("\n", 1)[0] + " ㈱ムロオ 人工倉庫\n" + text.splitlines()[-1][:88]
    # Blank outbound, keep inventory numeric and leave its loose blank unknown.
    line = text.splitlines()[-1]
    line = line[:74] + " " * 14 + "10".ljust(4) + " " * 3
    return text.rsplit("\n", 1)[0] + "\n" + line + "\n (2026/09/01)"


def test_pdf_batch_partial_failure_blank_outbound_and_saved_handoff(tmp_path, monkeypatch):
    app = create_app(tmp_path / "Data")
    client = TestClient(app, base_url="http://127.0.0.1")
    raw1 = document(END)
    raw2 = document(END - timedelta(days=1))
    monkeypatch.setattr(adapter, "page_source", lambda raw, *_: (b"", report_text(raw), 1))
    result = client.post(
        "/api/documents/batch",
        content=bundle(
            {
                "one.pdf": raw1,
                "two.pdf": raw2,
                "duplicate.pdf": raw1,
                "bad.pdf": b"not pdf",
                "other.csv": b"bad",
            }
        ),
    )
    assert result.status_code == 200
    assert len(result.json()["accepted"]) == 3 and len(result.json()["errors"]) == 2
    assert len(app.state.documents.list()) == 2
    doc = app.state.documents.read_local(result.json()["accepted"][0]["id"])
    inventory, ship = doc["extraction"]["rows"]
    assert inventory["loose_quantity"] == ""
    assert ship["case_quantity"] == ship["loose_quantity"] == "0"
    assert ship["source_outbound_case"] == ship["source_outbound_loose"] == ""
    inventory.update(case_quantity="10", loose_quantity="0", component_confirmed=True)
    ship["component_confirmed"] = True
    approved = app.state.documents.approve(
        doc["id"],
        {
            "actor": "人工",
            "confirmed": True,
            "revision": doc["extraction"]["revision"],
            "rows": [inventory, ship],
        },
    )
    csvs = {f["name"]: f["csv"].encode("utf-8-sig") for f in approved["approval"]["files"]}
    report = analyze_archive(bundle(csvs), tmp_path / "prepared.csv")
    assert report["files"]["shipment"] == report["files"]["inventory"] == 1
    assert (
        next(csv.DictReader(io.StringIO((tmp_path / "prepared.csv").read_text(encoding="utf-8"))))[
            "y"
        ]
        == "0"
    )


def test_28_pdf_individual_and_batch_dispatch_have_identical_daily_values(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "page_source", lambda raw, *_: (b"", report_text(raw), 1))
    results = []
    days = [END - timedelta(days=i) for i in reversed(range(28))]
    for batch in (False, True):
        app = create_app(tmp_path / str(batch))
        service = app.state.documents
        client = TestClient(app, base_url="http://127.0.0.1")
        if batch:
            response = client.post(
                "/api/documents/batch",
                content=bundle({f"{day}.pdf": document(day) for day in days}),
            )
            response.raise_for_status()
            ids = [r["id"] for r in response.json()["accepted"]]
        else:
            ids = [service.add(f"{day}.pdf", document(day))["id"] for day in days]
        for identifier in ids:
            doc = service.read_local(identifier, blank_current_zero=True)
            rows = doc["extraction"]["rows"]
            for row in rows:
                row["component_confirmed"] = True
            service.approve(
                identifier,
                {
                    "actor": "人工",
                    "confirmed": True,
                    "rows": rows,
                    "revision": doc["extraction"]["revision"],
                },
            )
            service.dispatch(identifier)
            if not batch:
                receipt = app.state.drop_folder.scan(force=True)["handled"][-1]
                assert receipt["status"] == "PROCESSED", receipt
        if batch:
            receipt = app.state.drop_folder.scan(force=True)["handled"][-1]
            assert receipt["status"] == "PROCESSED", receipt
        analysis_id = receipt["analysis_id"]
        paths = service.paths
        report = json.loads((paths.analysis / f"{analysis_id}.json").read_text("utf-8"))
        assert report["files"]["shipment"] == report["files"]["inventory"] == 28
        prepared = (paths.prepared / f"{analysis_id}.csv").read_bytes()
        demand = demand_forecast(
            paths, analysis_id, {"actor": "人工", "unit": "ボール", "confirmed": True}
        )
        assert demand["series"][0]["recognized_days"] == 28
        assert len(demand["predictions"]) == 14
        assert all(r["yhat"] == 0 for r in demand["predictions"])
        results.append(prepared)
    assert results[0] == results[1]


def test_csv_only_reference_http_and_inventory_only_retention(tmp_path):
    app = create_app(tmp_path / "Data")
    paths = app.state.documents.paths

    class Daily:
        def view(self, *_):
            return {}

    service = BusinessArchiveIntake(paths, Daily())
    first = service.ingest(bundle({"stock.csv": stock(END)}))
    assert first["files"]["inventory"] == 1 and first["files"]["shipment"] == 0
    report = service.ingest(
        bundle(
            {f"{END - timedelta(days=i)}.csv": shipment(END - timedelta(days=i)) for i in range(28)}
        )
    )
    assert report["files"]["inventory"] == 1
    client = TestClient(app, base_url="http://127.0.0.1")
    r = client.post(
        f"/api/field/{report['analysis_id']}/demand",
        json={"actor": "人工", "unit": "バラ", "confirmed": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["inventory"] is None and len(r.json()["predictions"]) == 14


def test_monthly_observed_rows_allow_forecast_but_never_imply_zero(tmp_path):
    import hashlib

    rows = ["倉庫,出荷日,JAN,数量"]
    for i in reversed(range(28)):
        rows.append(f"人工倉庫,{END - timedelta(days=i)},{JAN},0")
    raw = bundle({"monthly.csv": ("\n".join(rows) + "\n").encode()})
    source = tmp_path / "source.zip"
    source.write_bytes(raw)
    prepared = tmp_path / "prepared.csv"
    analyze_archive(raw, prepared)
    build, _ = build_daily_shipment(
        archive_path=source,
        prepared_path=prepared,
        handoff={"source_archive_sha256": hashlib.sha256(raw).hexdigest()},
        registration_id="synthetic",
        identities=[
            {
                "source_center": "人工倉庫",
                "jan": JAN,
                "canonical_product_id": "p",
                "forecast_center_id": "c",
            }
        ],
        zero_when_file_present=True,
    )
    assert build["series"][0]["forecast_eligible"]
    assert build["series"][0]["observed_day_count"] == 28
    assert build["series"][0]["confirmed_zero_day_count"] == 0
