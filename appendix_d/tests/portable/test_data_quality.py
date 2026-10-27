"""Quality checks never turn unreceived files into zero or rewrite prior forecasts."""

import csv
import io
import json
import time
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from test_saved_forecasts import CONFIRM, JAN, archive, process

from portable.api.app import create_app
from portable.api.data_quality import DataQuality
from portable.api.data_quality_store import QualityStore
from portable.api.forecast_capabilities import missing_capability
from portable.runtime.learning_backup import LearningBackup
from portable.runtime.paths import DataPaths

END = date(2026, 10, 13)
GAPS = {date(2026, 10, d) for d in (5, 8, 9, 11, 12)}


@pytest.fixture
def setup(tmp_path):
    app = create_app(tmp_path / "Data")
    return TestClient(app, base_url="http://localhost"), app.state.documents.paths


def upload(client, raw):
    response = client.post(
        "/api/business-archives", content=raw, headers={"Content-Type": "application/zip"}
    )
    assert response.status_code == 201, response.text
    return response.json()["analysis_id"]


def check(client, aid):
    response = client.get(f"/api/business-archives/{aid}/data-quality")
    assert response.status_code == 200, response.text
    return response.json()


def wait(client, aid):
    deadline = time.monotonic() + 20
    while True:
        value = client.get(f"/api/daily-runs/{aid}").json()
        if value["status"] != "PRODUCTION_RUNNING" or time.monotonic() >= deadline:
            return value
        time.sleep(0.05)


def rewrite(raw, operation):
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as old, zipfile.ZipFile(out, "w") as target:
        for item in old.infolist():
            result = operation(item.filename, old.read(item))
            if result is not None:
                target.writestr(item.filename, result)
    return out.getvalue()


def test_auto_check_all_gaps_filters_and_no_zero(setup):
    client, paths = setup
    aid = upload(client, archive([("神戸", END, GAPS)]))
    value = check(client, aid)
    assert value["missing_day_count"] == 5
    assert value["missing_record_count"] == 5
    assert value["valid_records"] == 23 and value["required_records"] == 28
    assert value["methods"]["C"]["enabled"]
    assert not value["methods"]["B"]["enabled"]
    persisted = QualityStore(paths).get("check", value["id"])
    assert {r["date"] for r in persisted["daily"] if r["state"] == "MISSING"} == {
        d.isoformat() for d in GAPS
    }
    assert all(r["quantity"] is None for r in persisted["daily"] if r["state"] == "MISSING")
    response = client.get(
        f"/api/data-quality/{value['id']}/issues",
        params={"warehouse": "神戸", "day": "2026-10-05", "code": "DATE_MISSING"},
    )
    assert response.json()["total"] == 1
    assert client.get(f"/api/data-quality/{value['id']}/issues?limit=1000").status_code == 422


def test_provisional_end_to_end_corrections_and_subsequent_normal(setup):
    client, paths = setup
    aid, initial = process(client, [("神戸", END, GAPS)])
    assert initial["status"] == "FORECAST_BLOCKED"
    quality = check(client, aid)
    payload = CONFIRM | {
        "forecast_mode": "C",
        "check_id": quality["id"],
        "confirm_provisional": True,
        "request_id": uuid.uuid4().hex,
    }
    response = client.post(f"/api/daily-runs/{aid}/advance", json=payload)
    assert response.status_code == 201, response.text
    current = wait(client, aid)
    assert current["status"] == "SUMMARY_CONFIRMATION_REQUIRED", current
    assert current["provisional"] and current["forecast_mode"] == "C"
    build = current["build_id"]
    saved = paths.formal_forecast / build
    before = {p.name: p.read_bytes() for p in saved.iterdir() if p.is_file()}
    daily = list(csv.DictReader(io.StringIO((saved / "daily.csv").read_text("utf-8-sig"))))
    assert all(r["y"] == "" for r in daily if r["ds"] in {d.isoformat() for d in GAPS})
    manifest = json.loads(before["manifest.json"])
    assert len(manifest["predictions"]) == 14
    assert all(r["yhat"] == 2 for r in manifest["predictions"])
    result = client.get(f"/api/field/{aid}/results").json()
    endpoint = f"/api/field/results/{result['result_id']}"
    shown = client.get(endpoint).json()
    assert shown["provisional"] and shown["quality_check_id"] == quality["id"]
    export = client.post(endpoint + "/download", json={"selected": None})
    assert "暫定予測" in export.content.decode("utf-8-sig")
    denied = client.post(f"/api/daily-runs/{aid}/daily-summary", json={})
    assert denied.status_code == 422 and "明示確認" in denied.text
    # Repeating the exact request must not create another immutable build.
    assert client.post(f"/api/daily-runs/{aid}/advance", json=payload).status_code == 201
    aid2, normal = process(client, [("神戸", END, set())])
    assert normal["status"] == "SUMMARY_CONFIRMATION_REQUIRED", normal
    assert not normal["provisional"] and normal["build_id"] != build
    assert check(client, aid2)["missing_day_count"] == 0
    old = client.get(f"/api/data-quality/{quality['id']}/issues?code=DATE_MISSING").json()
    assert all(r["state"] == "RESOLVED" for r in old["items"]), old
    assert before == {p.name: p.read_bytes() for p in saved.iterdir() if p.is_file()}
    old_result = client.get(f"/api/operator-results/production/{build}").json()
    assert old_result["provisional"]
    assert len(old_result["rows"]) == 14


def test_b_rejected_and_c_requires_latest_check_and_consent(setup):
    client, paths = setup
    aid, _ = process(client, [("神戸", END, GAPS)])
    url = f"/api/daily-runs/{aid}/advance"
    assert client.post(url, json=CONFIRM | {"forecast_mode": "B"}).status_code == 422
    q = check(client, aid)
    assert (
        client.post(url, json=CONFIRM | {"forecast_mode": "C", "check_id": q["id"]}).status_code
        == 422
    )
    service = DataQuality(paths)
    service.save_rules(
        {
            "actor": "人工IT",
            "reason": "受信予定を確認",
            "expected_version": service.rules()["id"],
            "rules": {"warehouses": []},
        }
    )
    response = client.post(
        url,
        json=CONFIRM
        | {
            "forecast_mode": "C",
            "check_id": q["id"],
            "request_id": uuid.uuid4().hex,
            "confirm_provisional": True,
        },
    )
    assert response.status_code == 422 and "変更" in response.text


@pytest.mark.parametrize(
    "stock_value,expected", [("0", None), ("", "QUANTITY_MISSING"), ("-1", "INVALID_VALUE")]
)
def test_stock_zero_blank_and_invalid_are_separate(setup, stock_value, expected):
    client, _ = setup
    raw = rewrite(
        archive([("神戸", END, set())]),
        lambda n, b: b.replace(b",10,", ("," + stock_value + ",").encode()) if "在庫" in n else b,
    )
    aid = upload(client, raw)
    value = check(client, aid)
    if expected:
        assert value["counts"].get(expected)
        assert value["provisional_series"] == 0
    else:
        assert not value["counts"].get("QUANTITY_MISSING")
        assert value["normal_series"] == 1


def test_calendar_assortment_future_and_schedule_are_explicit(setup):
    client, paths = setup
    aid = upload(client, archive([("神戸", END, GAPS)]))
    service = DataQuality(paths)
    service.save_rules(
        {
            "actor": "人工IT",
            "reason": "確認済みの休業・取扱期間",
            "expected_version": service.rules()["id"],
            "rules": {
                "warehouses": [
                    {
                        "warehouse": "神戸",
                        "from": "2026-01-01",
                        "closed_dates": ["2026-10-05"],
                        "products": [{"jan": JAN, "from": "2026-09-20", "to": None}],
                        "absence_means_zero": True,
                    }
                ]
            },
        }
    )
    q = service.check(aid)
    assert "2026-10-05" not in q["series"][0]["missing_dates"]
    assert q["series"][0]["required_records"] == 23  # 9/20..10/13 minus closure
    assert q["counts"]["FILE_MISSING"] == 4
    # A future source date is a data error, not 28 expected future receipts.
    aid2 = upload(client, archive([("杉戸", date(2026, 10, 29), set())]))
    future = service.check(aid2, checked_at=datetime(2026, 9, 1, tzinfo=UTC))
    assert future["counts"].get("INVALID_VALUE")
    assert not future["counts"].get("FILE_MISSING")


def test_admin_rules_conflict_protection_and_receipt_duplicates(setup, monkeypatch):
    client, paths = setup
    raw = archive([("神戸", END, set())])
    aid = upload(client, raw)
    duplicate = upload(client, raw)
    # Candidate ZIP identity may change when the history manifest is added; quantities must not.
    first = DataQuality(paths).store.get("check", check(client, aid)["id"])
    value = check(client, duplicate)
    second = DataQuality(paths).store.get("check", value["id"])
    assert first["daily"] == second["daily"]
    assert value["counts"]["DUPLICATE_RECORD"] == 1
    receipts = QualityStore(paths).list("receipt")
    assert len(receipts) == 2
    assert all(r["received_at"] for r in receipts)
    rule = {
        "actor": "IT",
        "reason": "人工確認",
        "expected_version": "default-calendar-v1",
        "rules": {"warehouses": []},
    }
    assert client.post("/api/data-quality/rules", json=rule).status_code == 403
    monkeypatch.setattr("portable.api.data_quality_routes.authorized", lambda *_: True)
    assert client.post("/api/data-quality/rules", json=rule).status_code == 201
    assert client.post("/api/data-quality/rules", json=rule).status_code == 422
    with pytest.raises(ValueError):
        QualityStore(paths).put("check", value["id"], duplicate, {"invalid": True})


def test_missing_warehouse_does_not_stop_healthy_warehouse(setup):
    client, _ = setup
    raw = rewrite(
        archive([("杉戸", END, set()), ("神戸", END, set())]),
        lambda n, b: None if "神戸" in n and "出荷" in n else b,
    )
    aid = upload(client, raw)
    locations = client.get(f"/api/business-archives/{aid}/formal-inventory").json()["centers"]
    response = client.post(
        f"/api/business-archives/{aid}/formal-inventory",
        json={
            "actor": "人工担当",
            "reason": "2倉庫確認",
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
    assert response.status_code == 201, response.text
    response = client.post(f"/api/daily-runs/{aid}/advance", json=CONFIRM)
    assert response.status_code == 201, response.text
    value = response.json()
    assert value["eligible_series_count"] == 1 and value["blocked_series_count"] == 1
    assert value["status"] in {"PRODUCTION_RUNNING", "SUMMARY_CONFIRMATION_REQUIRED"}
    assert check(client, aid)["counts"]["WAREHOUSE_MISSING"] == 1


def test_quality_db_backed_up_and_legacy_data_initializes(tmp_path):
    paths = DataPaths(tmp_path / "Data")
    paths.ensure()
    q = DataQuality(paths)
    rule = q.save_rules(
        {
            "actor": "IT",
            "reason": "復元試験",
            "expected_version": q.rules()["id"],
            "rules": {"warehouses": []},
        }
    )
    backup = LearningBackup(paths.root).create()
    with zipfile.ZipFile(backup) as z:
        assert "State/data-quality.sqlite3" in z.namelist()
    assert DataQuality(paths).rules()["id"] == rule["id"]


def test_missing_model_minimum_and_missing_weekday():
    import pandas as pd

    days = pd.date_range("2026-09-01", periods=35)
    frame = pd.DataFrame({"ds": days, "y": 2.0})
    frame.loc[frame.ds.dt.dayofweek == 2, "y"] = float("nan")
    assert not missing_capability(frame, days[-1])["supported"]
    assert not missing_capability(frame, days[-1], model="moving_average_28")["supported"]


def test_selected_candidate_not_replaced_and_metadata_tamper_rejected(setup, monkeypatch):
    client, paths = setup
    aid, _ = process(client, [("神戸", END, GAPS)])
    q = check(client, aid)
    monkeypatch.setattr(
        "portable.api.runtime_assignments.PortableRuntimeAssignments.preview_scopes",
        lambda *_: [
            {
                "status": "CANDIDATE_SELECTED",
                "selected_configuration": {"model_name": "moving_average_28"},
            }
        ],
    )
    response = client.post(
        f"/api/daily-runs/{aid}/advance",
        json=CONFIRM
        | {
            "forecast_mode": "C",
            "check_id": q["id"],
            "request_id": uuid.uuid4().hex,
            "confirm_provisional": True,
        },
    )
    assert response.status_code == 422 and "候補モデル" in response.text
    assert not list((paths.formal_forecast / "ProductionHandoffs").glob("*.json"))
    target = next(paths.formal_forecast.glob("portable-daily-*/manifest.json"))
    value = json.loads(target.read_text("utf-8"))
    value["provisional"] = True
    target.write_text(json.dumps(value), encoding="utf-8")
    from portable.api.formal_forecast_pipeline import PortableFormalForecastPipeline

    with pytest.raises(ValueError, match="品質"):
        PortableFormalForecastPipeline(paths)._verified_result(target)


def test_provisional_field_correction_and_quality_backup_restore(setup, tmp_path):
    client, paths = setup
    end = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    aid, _ = process(client, [("神戸", end, {end - timedelta(days=2)})])
    q = check(client, aid)
    response = client.post(
        f"/api/daily-runs/{aid}/advance",
        json=CONFIRM
        | {
            "forecast_mode": "C",
            "check_id": q["id"],
            "request_id": uuid.uuid4().hex,
            "confirm_provisional": True,
        },
    )
    assert response.status_code == 201, response.text
    state = wait(client, aid)
    rid = client.get(f"/api/field/{aid}/results").json()["result_id"]
    endpoint = f"/api/field/results/{rid}"
    original = client.get(endpoint).json()["rows"][0]
    edit = client.post(
        endpoint + "/review",
        json={
            "item": original["item"],
            "actor": "人工担当",
            "reason": "原本確認後の判断",
            "choice": "CHANGE",
            "quantity": 35,
            "revision": 0,
        },
    )
    assert edit.status_code == 201, edit.text
    current = client.get(endpoint).json()["rows"][0]
    assert current["review"]["quantity"] == 35 and current["forecast"] == original["forecast"]
    # Restoring the whole Data keeps quality history and its provisional marker.
    source = LearningBackup(paths.root)
    backup = source.create()
    target = tmp_path / "restored" / "Data"
    target.mkdir(parents=True)
    recovery = LearningBackup(target)
    recovery.stage(backup, confirm=True)
    restored_status = recovery.apply_pending()
    assert restored_status["status"] == "RESTORED", restored_status
    restored = TestClient(create_app(target), base_url="http://localhost")
    row = restored.get(endpoint).json()
    assert row["provisional"] and row["rows"][0]["review"]["quantity"] == 35
    assert QualityStore(DataPaths(target)).get("check", q["id"])["missing_day_count"] == 1
    assert state["provisional"]


def test_cached_checks_and_provenance(setup, monkeypatch):
    client, paths = setup
    aid = upload(client, archive([("神戸", END, GAPS)]))
    service = DataQuality(paths)
    first = service.check(aid)
    monkeypatch.setattr(service, "_sources", lambda *_: pytest.fail("unchanged input reparsed"))
    assert service.check(aid)["id"] == first["id"]
    prepared = paths.prepared / f"{aid}.csv"
    original = prepared.read_bytes()
    prepared.write_bytes(original + b"2026-10-13,silent:change,3\n")
    with pytest.raises(ValueError, match="集計"):
        service.check(aid)
    prepared.write_bytes(original)
    source = paths.input / f"{aid}.zip"
    source.write_bytes(source.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="原本ZIP"):
        service.check(aid)


def test_shipment_only_provisional_and_no_inventory_fabrication(setup):
    client, _ = setup
    raw = rewrite(archive([("神戸", END, GAPS)]), lambda n, b: None if "在庫" in n else b)
    aid = upload(client, raw)
    q = check(client, aid)
    response = client.post(
        f"/api/field/{aid}/demand",
        json={
            "actor": "人工担当",
            "unit": "ボール",
            "confirmed": True,
            "forecast_mode": "C",
            "check_id": q["id"],
            "confirm_provisional": True,
        },
    )
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["provisional"] and value["inventory"] is None
    assert not value["inventory_risk_evaluated"]
    assert len(value["predictions"]) == 14


def test_abnormal_stock_units_master_warning_and_exclusion(setup):
    from portable.api.product_exclusions import ProductExclusions

    client, paths = setup
    out = io.BytesIO()
    with (
        zipfile.ZipFile(out, "w") as z,
        zipfile.ZipFile(io.BytesIO(archive([("神戸", END, set())]))) as raw,
    ):
        for m in raw.infolist():
            if "在庫" not in m.filename:
                z.writestr(m.filename, raw.read(m))
        for day, qty in [(END - timedelta(days=1), 100), (END, 10)]:
            text = (
                "倉庫,基準日,JAN,商品名,在庫数量,賞味期限,正規化単位\n"
                f"神戸,{day},{JAN},人工商品,{qty},2027-01-01,CASE\n"
            )
            z.writestr(f"stock-{day}.csv", text.encode("utf-8"))
    aid = upload(client, out.getvalue())
    service = DataQuality(paths)
    service.save_rules(
        {
            "actor": "IT",
            "reason": "人工在庫変動を点検",
            "expected_version": service.rules()["id"],
            "rules": {
                "warehouses": [
                    {
                        "warehouse": "神戸",
                        "master_jans": [],
                        "abnormal_change_cases": "20",
                        "absence_means_zero": True,
                    }
                ]
            },
        }
    )
    checked = service.check(aid)
    assert checked["counts"]["ABNORMAL_CHANGE"] == 1
    assert any(i["kind"] == "master" for i in checked["issues"])
    assert service.rules(as_of=datetime(2020, 1, 1, tzinfo=UTC))["id"] == "default-calendar-v1"
    ProductExclusions(paths).save(
        {
            "actor": "IT",
            "products": [
                {"jan": JAN, "product_name": "人工商品", "exclude": True, "reason": "人工対象外"}
            ],
        }
    )
    excluded = service.check(aid)
    assert not excluded["series"] and excluded["missing_record_count"] == 0


def test_reference_backtest_never_scores_missing_actual_as_zero(tmp_path):
    import pandas as pd

    from portable.api.business_archive import run_reference_backtest

    days = pd.date_range("2026-09-01", periods=35)
    frame = pd.DataFrame({"ds": days.strftime("%Y-%m-%d"), "unique_id": "TEST:" + JAN, "y": 2})
    frame = frame[frame.ds != days[-2].strftime("%Y-%m-%d")]
    path = tmp_path / "prepared.csv"
    frame.to_csv(path, index=False)
    result = run_reference_backtest(path, tmp_path, "synthetic")
    assert result["centers"][0]["points"] == 6
    assert result["centers"][0]["unobserved_actual_points"] == 1
    assert result["centers"][0]["wape"] == 0


def test_received_file_without_product_is_not_inventory_zero(setup):
    client, paths = setup
    missing = END - timedelta(days=1)
    raw = rewrite(
        archive([("神戸", END, set())]),
        lambda n, b: (
            b.splitlines()[0] + b"\n" if "出荷" in n and missing.strftime("%Y%m%d") in n else b
        ),
    )
    aid = upload(client, raw)
    service = DataQuality(paths)
    service.save_rules(
        {
            "actor": "IT",
            "reason": "商品省略の0は未確認",
            "expected_version": service.rules()["id"],
            "rules": {"warehouses": [{"warehouse": "神戸", "absence_means_zero": False}]},
        }
    )
    result = service.check(aid)
    issues = [i for i in result["issues"] if i["date"] == missing.isoformat()]
    assert any(i["code"] == "PRODUCT_MISSING" and i["kind"] == "shipment" for i in issues)
    assert not any(i["code"] == "FILE_MISSING" for i in issues)
    row = next(r for r in result["daily"] if r["date"] == missing.isoformat())
    assert row["state"] == "MISSING" and row["quantity"] is None


def test_mixed_warehouse_origins_do_not_silently_shift_forecast(setup):
    client, paths = setup
    _, state = process(client, [("杉戸", END, set()), ("神戸", END - timedelta(days=1), set())])
    assert state["eligible_series_count"] == 1 and state["blocked_series_count"] == 1
    manifest = json.loads(
        (paths.formal_forecast / state["build_id"] / "manifest.json").read_text("utf-8")
    )
    older = next(s for s in manifest["series"] if s["source_center"] == "神戸")
    assert "FORECAST_ORIGIN_UNALIGNED" in older["blocking_reasons"]
    assert manifest["train_end"] == END.isoformat()
