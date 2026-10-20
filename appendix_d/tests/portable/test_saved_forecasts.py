"""Completed warehouse forecasts stay readable after another intake is blocked."""

import csv
import io
import time
import zipfile
from datetime import date, timedelta

from fastapi.testclient import TestClient

from portable.api.app import create_app

JAN = "4901234567894"
CONFIRM = {
    "actor": "人工担当",
    "reason": "原本と範囲確認",
    "confirm_pilot_scope": True,
    "confirm_quantity_reconciliation": True,
    "confirm_identity_bridge": True,
    "confirm_zero_policy": True,
}


def archive(centers):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for center, end, missing in centers:
            day = date(2026, 9, 1)
            while day <= end:
                if day not in missing:
                    text = ("出荷日,納品日,商品名,JAN,数量\n"
                            f"{day:%Y/%m/%d},{day:%Y/%m/%d},人工商品,{JAN},2\n")
                    z.writestr(f"{center}日時出荷_{day:%Y%m%d}.csv", text.encode("cp932"))
                day += timedelta(days=1)
            z.writestr(
                f"{center}日時在庫_{end:%Y%m%d}.csv",
                f"商品コード,商品名,明細バラ数,賞味期限\n{JAN},人工商品,10,2026/12/31\n".encode(
                    "cp932"
                ),
            )
    return output.getvalue()


def process(client, centers):
    r = client.post(
        "/api/business-archives",
        content=archive(centers),
        headers={"Content-Type": "application/zip"},
    )
    assert r.status_code == 201, r.text
    aid = r.json()["analysis_id"]
    locations = client.get(f"/api/business-archives/{aid}/formal-inventory").json()["centers"]
    r = client.post(
        f"/api/business-archives/{aid}/formal-inventory",
        json={
            "actor": "人工担当",
            "reason": "数量確認",
            "confirm_case": True,
            "locations": [
                {
                    "source_center": c["source_center"],
                    "location_code": c["source_center"],
                    "location_name": c["source_center"],
                    "snapshot_time": "16:00",
                }
                for c in locations
            ],
        },
    )
    assert r.status_code == 201, r.text
    r = client.post(f"/api/daily-runs/{aid}/advance", json=CONFIRM)
    assert r.status_code == 201, r.text
    value = r.json()
    deadline = time.monotonic() + 15
    while value["status"] == "PRODUCTION_RUNNING" and time.monotonic() < deadline:
        time.sleep(0.05)
        value = client.get(f"/api/daily-runs/{aid}").json()
    return aid, value


def test_sugito_saved_result_survives_kobe_missing_days_and_restart(tmp_path):
    client = TestClient(create_app(tmp_path), base_url="http://localhost")
    _, sugito = process(client, [("杉戸", date(2026, 10, 13), set())])
    assert sugito["status"] == "SUMMARY_CONFIRMATION_REQUIRED", sugito
    reference = sugito["build_id"]
    endpoint = f"/api/operator-results/production/{reference}"
    original = client.get(endpoint).json()["rows"]
    assert len(original) == 14
    feedback = client.post(
        endpoint + "/feedback",
        json={
            "unique_id": original[0]["unique_id"],
            "target_date": original[0]["target_date"],
            "actor": "人工担当",
            "reason": "原本比較",
            "rating": "OK",
            "comment": "保存版確認",
        },
    )
    assert feedback.status_code == 201, feedback.text
    before = {
        p.name: p.read_bytes()
        for p in (tmp_path / "FormalForecast" / reference).iterdir()
        if p.is_file()
    }
    missing = {date(2026, 10, n) for n in (5, 8, 9, 11, 12)}
    _, kobe = process(client, [("神戸", date(2026, 10, 15), missing)])
    assert kobe["status"] == "FORECAST_BLOCKED", kobe
    assert kobe["blockers"][0]["recognized_required_days"] == 23
    assert len(kobe["blockers"][0]["missing_required_dates"]) == 5
    catalog = client.get("/api/saved-forecasts").json()
    assert catalog["warehouses"] == ["杉戸"]
    saved = catalog["items"][0]
    assert saved["reference"] == reference
    assert saved["inventory_date"] == "2026-10-13"
    assert saved["period"] == ["2026-10-14", "2026-10-27"]
    scoped = client.get(endpoint, params={"warehouse": "杉戸"})
    assert scoped.status_code == 200
    assert [r["yhat"] for r in scoped.json()["rows"]] == [r["yhat"] for r in original]
    assert scoped.json()["history"][0]["comment"] == "保存版確認"
    assert client.get(endpoint, params={"warehouse": "神戸"}).status_code == 404
    csv_result = client.post(endpoint + "/download?warehouse=杉戸", json={"selected": None})
    assert csv_result.status_code == 200
    assert len(list(csv.reader(io.StringIO(csv_result.content.decode("utf-8-sig"))))) == 15
    result = client.get(f"/api/field/saved-forecasts/{reference}/results")
    assert result.status_code == 200, result.text
    rid = result.json()["result_id"]
    page = client.get(f"/api/field/results/{rid}", params={"warehouse": "杉戸"}).json()
    assert page["rows"][0]["forecast"] is not None
    assert page["rows"][0]["period"] == saved["period"]
    assert page["counts"]["forecastable"] == 1
    reopened = TestClient(create_app(tmp_path), base_url="http://localhost")
    assert reopened.get("/api/saved-forecasts?warehouse=杉戸").json()["items"][0] == saved
    assert (
        reopened.get(f"/api/field/saved-forecasts/{reference}/results").json()["result_id"] == rid
    )
    malformed = tmp_path / "FormalForecast" / ("portable-daily-" + "f" * 64)
    malformed.mkdir()
    (malformed / "manifest.json").write_text("[]", encoding="utf-8")
    (malformed / "daily.csv").write_bytes(b"")
    (malformed / "predictions.json").write_bytes(b"[]")
    remaining = reopened.get("/api/saved-forecasts").json()
    assert remaining["items"][0] == saved
    assert remaining["unavailable_count"] == 1
    assert before == {
        p.name: p.read_bytes()
        for p in (tmp_path / "FormalForecast" / reference).iterdir()
        if p.is_file()
    }


def test_partial_forecast_lists_only_completed_warehouses_and_scopes_downloads(tmp_path):
    client = TestClient(create_app(tmp_path), base_url="http://localhost")
    missing = {date(2026, 10, n) for n in (5, 8, 9, 11, 12)}
    _, value = process(
        client, [("杉戸", date(2026, 10, 13), set()), ("神戸", date(2026, 10, 15), missing)]
    )
    assert value["eligible_series_count"] == 1
    assert value["blocked_series_count"] == 1
    catalog = client.get("/api/saved-forecasts").json()
    assert catalog["warehouses"] == ["杉戸"]
    assert catalog["unavailable_count"] == 0
    reference = value["build_id"]
    rid = client.get(f"/api/field/saved-forecasts/{reference}/results").json()["result_id"]
    page = client.get(f"/api/field/results/{rid}?warehouse=杉戸").json()
    assert page["counts"]["total"] == page["counts"]["forecastable"] == 1
    export = client.post(f"/api/field/results/{rid}/export", json={"warehouse": "杉戸"})
    assert export.status_code == 201
    data = client.get(export.json()["download_href"]).content.decode("utf-8-sig")
    assert "神戸" not in data and "杉戸" in data
    assert (
        client.get(f"/api/operator-results/production/{reference}?warehouse=神戸").status_code
        == 404
    )


def test_saved_catalog_rejects_corruption_and_keeps_warehouse_filter(tmp_path):
    client = TestClient(create_app(tmp_path), base_url="http://localhost")
    _, value = process(
        client, [("杉戸", date(2026, 10, 13), set()), ("神戸", date(2026, 10, 15), set())]
    )
    catalog = client.get("/api/saved-forecasts").json()
    assert set(catalog["warehouses"]) == {"杉戸", "神戸"}
    scoped = client.get("/api/saved-forecasts?warehouse=杉戸&limit=1").json()
    assert scoped["total"] == 1 and len(scoped["items"]) == 1
    ref = value["build_id"]
    response = client.post(
        f"/api/operator-results/production/{ref}/download?warehouse=杉戸",
        json={"selected": [JAN + "::神戸"]},
    )
    assert response.status_code == 422
    path = tmp_path / "FormalForecast" / ref / "predictions.json"
    path.write_bytes(path.read_bytes() + b"tampered")
    bad = client.get("/api/saved-forecasts").json()
    assert not bad["items"] and bad["unavailable_count"] == 1
    assert client.get("/api/field/saved-forecasts/../../results").status_code == 404
