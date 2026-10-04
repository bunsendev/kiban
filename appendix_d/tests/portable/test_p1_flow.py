"""P1 acceptance tests: persistence, deterministic baseline, recovery and local boundary."""

import base64
import csv
import hashlib
import io
import json
import os
import secrets
import subprocess
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.api.business_archive import analyze_archive, run_reference_backtest
from portable.api.formal_shipment_daily import build_daily_shipment
from portable.api.store import RunStore
from portable.launcher.main import available_ports, request_json, start_server, stop_server
from portable.runtime.paths import DataPaths
from portable.runtime.windows import AlreadyRunning, ChildJob, SingleInstance


def synthetic_csv() -> bytes:
    rows = ["ds,unique_id,y"]
    for uid, offset in [("SYNTHETIC-001", 0), ("SYNTHETIC-002", 10)]:
        for day in range(28):
            date = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)).date()
            rows.append(f"{date},{uid},{day % 7 + offset}")
    return ("\n".join(rows) + "\n").encode()


def business_zip(marker: str = "") -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for offset in range(35):
            day = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=offset)).date()
            rows = ["出荷日,納品日,商品名,JAN,数量"]
            rows.append(f"{day:%Y/%m/%d},{day:%Y/%m/%d},人工商品,4900000000001,{offset % 7}")
            if offset == 0:
                rows.append(f"{day:%Y/%m/%d},{day:%Y/%m/%d},確認商品,900000000001,1")
            archive.writestr(
                f"data/神戸日時出荷_{day:%Y%m%d}.csv", ("\n".join(rows) + "\n").encode("cp932")
            )
        inventory = (
            "商品コード,商品名,明細バラ数,賞味期限\n"
            "4900000000001,人工商品,10,2026/02/01\n"
            "4900000000002,未対応商品,5,2026/02/01\n"
            "2,異常商品,1,\n"
        )
        archive.writestr("data/神戸日時在庫_20260204.csv", inventory.encode("cp932"))
        if marker:
            archive.writestr(f"data/{marker}.txt", marker.encode())
    return target.getvalue()


def formal_inventory_zip(*, latest_expiry: str = "2026/04/30") -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        shipment = (
            "出荷日,納品日,商品名,JAN,数量\n"
            "2026/02/04,2026/02/04,正式商品,4901234567894,2\n"
        )
        archive.writestr("data/神戸日時出荷_20260204.csv", shipment.encode("cp932"))
        older = (
            "商品コード,商品名,明細バラ数,賞味期限\n"
            "4901234567894,正式商品,3,\n"
        )
        latest = (
            "商品コード,商品名,明細バラ数,賞味期限\n"
            f"4901234567894,正式商品,5,{latest_expiry}\n"
        )
        archive.writestr("data/神戸日時在庫_20260203.csv", older.encode("cp932"))
        archive.writestr("data/神戸日時在庫_20260204.csv", latest.encode("cp932"))
    return target.getvalue()


def _jan13(serial: int) -> str:
    body = f"490123456{serial:03d}"
    check = (10 - sum(
        int(value) * (1 if index % 2 == 0 else 3)
        for index, value in enumerate(body)
    ) % 10) % 10
    return f"{body}{check}"


def pilot_inventory_zip(count: int = 10) -> bytes:
    target = io.BytesIO()
    shipment_rows = ["出荷日,納品日,商品名,JAN,数量"]
    inventory_rows = ["商品コード,商品名,明細バラ数,賞味期限"]
    for index in range(count):
        jan = _jan13(index)
        shipment_rows.append(f"2026/02/04,2026/02/04,正式商品{index},{jan},{index + 1}")
        inventory_rows.append(f"{jan},正式商品{index},{index + 1},2026/04/30")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "data/神戸日時出荷_20260204.csv", "\n".join(shipment_rows).encode("cp932")
        )
        archive.writestr(
            "data/神戸日時在庫_20260204.csv", "\n".join(inventory_rows).encode("cp932")
        )
    return target.getvalue()


def pilot_forecast_zip(count: int = 10, *, invalid_recent: bool = False) -> bytes:
    target = io.BytesIO()
    inventory_rows = ["商品コード,商品名,明細バラ数,賞味期限"]
    for index in range(count):
        jan = _jan13(index)
        inventory_rows.append(f"{jan},正式商品{index},{index + 1},2026/04/30")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for offset in range(35):
            day = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=offset)).date()
            shipment_rows = ["出荷日,納品日,商品名,JAN,数量"]
            for index in range(count):
                jan = _jan13(index)
                quantity = "不正" if invalid_recent and offset == 34 and index == 0 else index + 1
                shipment_rows.append(
                    f"{day:%Y/%m/%d},{day:%Y/%m/%d},正式商品{index},{jan},{quantity}"
                )
            archive.writestr(
                f"data/神戸日時出荷_{day:%Y%m%d}.csv",
                "\n".join(shipment_rows).encode("cp932"),
            )
        archive.writestr(
            "data/神戸日時在庫_20260204.csv", "\n".join(inventory_rows).encode("cp932")
        )
    return target.getvalue()


def multi_center_forecast_zip(count: int = 10) -> bytes:
    target = io.BytesIO()
    centers = (("神戸", "2026/02/10"), ("加須", "2026/04/30"))
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for center, expiry in centers:
            inventory_rows = ["商品コード,商品名,明細バラ数,賞味期限"]
            for index in range(count):
                jan = _jan13(index)
                inventory_quantity = 100 + index if center == "神戸" else index + 2
                inventory_rows.append(
                    f"{jan},正式商品{index},{inventory_quantity},{expiry}"
                )
            for offset in range(35):
                day = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=offset)).date()
                shipment_rows = ["出荷日,納品日,商品名,JAN,数量"]
                for index in range(count):
                    jan = _jan13(index)
                    shipment_rows.append(
                        f"{day:%Y/%m/%d},{day:%Y/%m/%d},正式商品{index},{jan},{index + 1}"
                    )
                archive.writestr(
                    f"data/{center}日時出荷_{day:%Y%m%d}.csv",
                    "\n".join(shipment_rows).encode("cp932"),
                )
            archive.writestr(
                f"data/{center}日時在庫_20260204.csv",
                "\n".join(inventory_rows).encode("cp932"),
            )
    return target.getvalue()


def approved_formal_pipeline(client: TestClient, raw: bytes) -> dict:
    report = client.post(
        "/api/business-archives", content=raw,
        headers={"Content-Type": "application/zip"},
    ).json()
    handoff = client.post(
        f"/api/business-archives/{report['analysis_id']}/formal-inventory",
        json={
            "actor": "現場担当者", "reason": "最新在庫とCASEを確認", "confirm_case": True,
            "locations": [{"source_center": "神戸", "location_code": "KOBE",
                           "location_name": "神戸倉庫", "snapshot_time": "16:00"}],
        },
    ).json()
    pipeline_view = client.get(
        f"/api/formal-inventory/{handoff['handoff_id']}/pipeline"
    ).json()
    registered = client.post(
        f"/api/formal-inventory/{handoff['handoff_id']}/pipeline",
        json={
            "actor": "試験管理者", "reason": "10商品のPilot Scopeを確認",
            "confirm_pilot_scope": True,
            "selections": [{"source_center": "神戸",
                            "jans": pipeline_view["locations"][0]["jans"]}],
        },
    ).json()
    job = registered["jobs"][0]
    approved = client.post(
        "/api/formal-inventory/pipeline/"
        f"{registered['registration_id']}/jobs/{job['job_id']}/approve",
        json={"actor": "承認管理者", "reason": "原本数量と隔離0件を確認",
              "expected_revision": 0},
    ).json()
    assert approved["status"] == "APPROVED"
    return approved


def approved_multi_center_pipeline(client: TestClient) -> dict:
    report = client.post(
        "/api/business-archives", content=multi_center_forecast_zip(),
        headers={"Content-Type": "application/zip"},
    ).json()
    handoff = client.post(
        f"/api/business-archives/{report['analysis_id']}/formal-inventory",
        json={
            "actor": "現場担当者", "reason": "2倉庫の最新在庫とCASEを確認",
            "confirm_case": True,
            "locations": [
                {"source_center": "神戸", "location_code": "KOBE",
                 "location_name": "神戸倉庫", "snapshot_time": "16:00"},
                {"source_center": "加須", "location_code": "KAZO",
                 "location_name": "加須倉庫", "snapshot_time": "16:00"},
            ],
        },
    ).json()
    pipeline_view = client.get(
        f"/api/formal-inventory/{handoff['handoff_id']}/pipeline"
    ).json()
    registered = client.post(
        f"/api/formal-inventory/{handoff['handoff_id']}/pipeline",
        json={
            "actor": "試験管理者", "reason": "2倉庫のPilot Scopeを確認",
            "confirm_pilot_scope": True,
            "selections": [
                {"source_center": item["source_center"], "jans": item["jans"]}
                for item in pipeline_view["locations"]
            ],
        },
    ).json()
    approved = None
    for job in registered["jobs"]:
        approved = client.post(
            "/api/formal-inventory/pipeline/"
            f"{registered['registration_id']}/jobs/{job['job_id']}/approve",
            json={"actor": "承認管理者", "reason": "原本数量と隔離0件を確認",
                  "expected_revision": 0},
        ).json()
    assert approved["status"] == "APPROVED"
    return approved


def test_business_archive_preflight_and_reference_backtest(tmp_path: Path):
    prepared = tmp_path / "prepared.csv"
    report = analyze_archive(business_zip(), prepared)
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["rows"] == {
        "shipment": 36,
        "inventory": 3,
        "auto_confirmed": 36,
        "review_required": 2,
        "quarantined": 1,
    }
    assert report["products"]["inventory_codes_matched_to_shipment_jan"] == 1
    assert report["reasons"]["INVENTORY_CODE_UNMATCHED"] == 1
    assert "EXPIRY_MISSING" not in report["reasons"]
    assert sum(item["count"] for item in report["issues"]) == 3
    assert report["center_windows"] == [
        {
            "center": "神戸",
            "latest_date": "2026-02-04",
            "backtest_ready": True,
            "missing_recent_days": 0,
        }
    ]
    result = run_reference_backtest(prepared, tmp_path, "analysis")
    assert result["provider"] == "builtin-baseline/seasonal_naive_7"
    assert result["centers"][0]["points"] == 7
    assert result["centers"][0]["wape"] == 0.0


def test_business_archive_api_flow(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    response = client.post(
        "/api/business-archives",
        content=business_zip(),
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 201, response.text
    report = response.json()
    analysis_id = report["analysis_id"]
    assert client.get("/api/business-archives").json()[0]["analysis_id"] == analysis_id
    assert client.get(f"/api/business-archives/{analysis_id}").json() == report
    backtest = client.post(f"/api/business-archives/{analysis_id}/backtest")
    assert backtest.status_code == 201, backtest.text
    assert backtest.json()["centers"][0]["wape"] == 0.0


def test_operator_decision_is_append_only_rebuilds_data_and_reuses_mapping(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    report = client.post(
        "/api/business-archives",
        content=business_zip(),
        headers={"Content-Type": "application/zip"},
    ).json()
    issue = next(item for item in report["issues"] if item["reason"] == "JAN_12_DIGITS")
    immutable_report = tmp_path / "Analysis" / f"{report['analysis_id']}.json"
    report_bytes = immutable_report.read_bytes()
    response = client.post(
        f"/api/business-archives/{report['analysis_id']}/issues/{issue['issue_id']}",
        json={
            "action": "MAP_JAN",
            "corrected_jan": "4900000000002",
            "note": "商品マスタで確認",
            "remember": True,
        },
    )
    assert response.status_code == 201, response.text
    decided = response.json()
    assert decided["review"]["resolved_rows"] == 1
    assert decided["review"]["pending_rows"] == 2
    assert issue["issue_id"] in (
        tmp_path / "Decisions" / f"{report['analysis_id']}.jsonl"
    ).read_text(encoding="utf-8")
    reviewed = pd.read_csv(tmp_path / "Prepared" / f"{report['analysis_id']}-reviewed.csv")
    assert "神戸:4900000000002" in set(reviewed["unique_id"])
    assert immutable_report.read_bytes() == report_bytes

    revised = client.post(
        f"/api/business-archives/{report['analysis_id']}/issues/{issue['issue_id']}",
        json={"action": "EXCLUDE", "note": "再確認して除外"},
    )
    assert revised.status_code == 201
    reviewed = pd.read_csv(tmp_path / "Prepared" / f"{report['analysis_id']}-reviewed.csv")
    assert "神戸:4900000000002" not in set(reviewed["unique_id"])
    history = client.get(
        f"/api/business-archives/{report['analysis_id']}/decision-history"
    ).json()
    assert [item["action"] for item in history] == ["MAP_JAN", "EXCLUDE"]

    second = client.post(
        "/api/business-archives",
        content=business_zip("second"),
        headers={"Content-Type": "application/zip"},
    ).json()
    remembered = next(item for item in second["issues"] if item["reason"] == "JAN_12_DIGITS")
    assert remembered["decision"]["source"] == "REMEMBERED_RULE"
    assert remembered["decision"]["corrected_jan"] == "4900000000002"


def test_operator_decision_rejects_invalid_correction(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    report = client.post(
        "/api/business-archives",
        content=business_zip(),
        headers={"Content-Type": "application/zip"},
    ).json()
    issue = next(item for item in report["issues"] if item["reason"] == "JAN_12_DIGITS")
    response = client.post(
        f"/api/business-archives/{report['analysis_id']}/issues/{issue['issue_id']}",
        json={"action": "MAP_JAN", "corrected_jan": "123"},
    )
    assert response.status_code == 422
    assert not (tmp_path / "Decisions" / f"{report['analysis_id']}.jsonl").exists()


def test_latest_inventory_is_validated_and_packaged_for_formal_intake(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    report = client.post(
        "/api/business-archives",
        content=formal_inventory_zip(),
        headers={"Content-Type": "application/zip"},
    ).json()
    view = client.get(
        f"/api/business-archives/{report['analysis_id']}/formal-inventory"
    ).json()
    assert view == {
        "centers": [{"source_center": "神戸", "latest_date": "2026-02-04"}],
        "latest": None,
    }
    payload = {
        "actor": "現場担当者",
        "reason": "最新在庫、拠点、基準時刻、CASEを確認",
        "confirm_case": True,
        "locations": [{
            "source_center": "神戸",
            "location_code": "KOBE",
            "location_name": "神戸倉庫",
            "snapshot_time": "16:00",
        }],
    }
    response = client.post(
        f"/api/business-archives/{report['analysis_id']}/formal-inventory", json=payload
    )
    assert response.status_code == 201, response.text
    handoff = response.json()
    assert handoff["status"] == "READY_FOR_FORMAL_INTAKE"
    assert handoff["normalized_unit"] == "CASE"
    assert handoff["files"][0]["source_row_count"] == 1
    assert handoff["files"][0]["accepted_row_count"] == 1
    assert handoff["files"][0]["quantity_cases"] == "5"
    assert handoff["files"][0]["snapshot_at"] == "2026-02-04T07:00:00+00:00"
    download = client.get(f"/api/formal-inventory/{handoff['handoff_id']}/download")
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as package:
        assert json.loads(package.read("manifest.json"))["handoff_id"] == handoff["handoff_id"]
        csv_name = handoff["files"][0]["candidate_file"]
        candidate = package.read(csv_name).decode("utf-8-sig")
        assert "4901234567894,KOBE,2026-04-30,5,2026-02-04T07:00:00+00:00" in candidate
    repeated = client.post(
        f"/api/business-archives/{report['analysis_id']}/formal-inventory", json=payload
    ).json()
    assert repeated["handoff_id"] == handoff["handoff_id"]


def test_formal_inventory_stays_blocked_for_unresolved_latest_row(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    report = client.post(
        "/api/business-archives",
        content=formal_inventory_zip(latest_expiry=""),
        headers={"Content-Type": "application/zip"},
    ).json()
    response = client.post(
        f"/api/business-archives/{report['analysis_id']}/formal-inventory",
        json={
            "actor": "現場担当者",
            "reason": "欠損を確認",
            "confirm_case": True,
            "locations": [{"source_center": "神戸", "location_code": "KOBE",
                           "location_name": "神戸倉庫", "snapshot_time": "16:00"}],
        },
    )
    assert response.status_code == 201
    handoff = response.json()
    assert handoff["status"] == "BLOCKED"
    assert handoff["blockers"][0]["reason_codes"] == ["EXPIRY_UNRESOLVED"]
    assert client.get(f"/api/formal-inventory/{handoff['handoff_id']}/download").status_code == 404


def test_formal_inventory_requires_explicit_case_confirmation(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    report = client.post(
        "/api/business-archives", content=formal_inventory_zip(),
        headers={"Content-Type": "application/zip"},
    ).json()
    response = client.post(
        f"/api/business-archives/{report['analysis_id']}/formal-inventory",
        json={"actor": "担当", "reason": "確認", "confirm_case": False, "locations": []},
    )
    assert response.status_code == 422
    assert "CASE" in response.json()["detail"]


def test_formal_inventory_runs_unified_inbox_worker_and_explicit_approval(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    report = client.post(
        "/api/business-archives", content=pilot_inventory_zip(),
        headers={"Content-Type": "application/zip"},
    ).json()
    handoff = client.post(
        f"/api/business-archives/{report['analysis_id']}/formal-inventory",
        json={
            "actor": "現場担当者", "reason": "最新在庫とCASEを確認", "confirm_case": True,
            "locations": [{"source_center": "神戸", "location_code": "KOBE",
                           "location_name": "神戸倉庫", "snapshot_time": "16:00"}],
        },
    ).json()
    pipeline_view = client.get(
        f"/api/formal-inventory/{handoff['handoff_id']}/pipeline"
    ).json()
    assert len(pipeline_view["locations"][0]["jans"]) == 10
    response = client.post(
        f"/api/formal-inventory/{handoff['handoff_id']}/pipeline",
        json={
            "actor": "試験管理者", "reason": "10商品のPilot Scopeを確認",
            "confirm_pilot_scope": True,
            "selections": [{"source_center": "神戸",
                            "jans": pipeline_view["locations"][0]["jans"]}],
        },
    )
    assert response.status_code == 201, response.text
    registered = response.json()
    assert registered["status"] == "APPROVAL_REQUIRED"
    assert registered["jobs"][0]["accepted_row_count"] == 10
    assert registered["jobs"][0]["quarantined_row_count"] == 0
    assert registered["jobs"][0]["reconciliation_matched"] is True
    assert registered["jobs"][0]["normalized_quantity_cases"] == "55"
    job = registered["jobs"][0]
    approved_response = client.post(
        "/api/formal-inventory/pipeline/"
        f"{registered['registration_id']}/jobs/{job['job_id']}/approve",
        json={"actor": "承認管理者", "reason": "原本数量と隔離0件を確認",
              "expected_revision": 0},
    )
    assert approved_response.status_code == 201, approved_response.text
    approved = approved_response.json()
    assert approved["status"] == "APPROVED"
    assert approved["jobs"][0]["snapshot_id"].startswith("inventory-snapshot-")
    assert approved["forecast_update_status"] == "WAITING_FOR_FORMAL_SHIPMENT_DAILY_BUILD"

    restarted = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    persisted = restarted.get(
        f"/api/formal-inventory/{handoff['handoff_id']}/pipeline"
    ).json()["latest"]
    assert persisted["status"] == "APPROVED"


def test_formal_pipeline_rejects_unconfirmed_or_too_small_scope(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    report = client.post(
        "/api/business-archives", content=pilot_inventory_zip(),
        headers={"Content-Type": "application/zip"},
    ).json()
    handoff = client.post(
        f"/api/business-archives/{report['analysis_id']}/formal-inventory",
        json={
            "actor": "担当", "reason": "確認", "confirm_case": True,
            "locations": [{"source_center": "神戸", "location_code": "KOBE",
                           "location_name": "神戸倉庫", "snapshot_time": "16:00"}],
        },
    ).json()
    response = client.post(
        f"/api/formal-inventory/{handoff['handoff_id']}/pipeline",
        json={"actor": "管理者", "reason": "確認", "confirm_pilot_scope": False,
              "selections": [{"source_center": "神戸", "jans": [_jan13(0)]}]},
    )
    assert response.status_code == 422
    assert not list((tmp_path / "FormalInventory" / "Registrations").glob("*.json"))


def test_formal_pipeline_rejects_modified_candidate(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    report = client.post(
        "/api/business-archives", content=pilot_inventory_zip(),
        headers={"Content-Type": "application/zip"},
    ).json()
    handoff = client.post(
        f"/api/business-archives/{report['analysis_id']}/formal-inventory",
        json={
            "actor": "担当", "reason": "確認", "confirm_case": True,
            "locations": [{"source_center": "神戸", "location_code": "KOBE",
                           "location_name": "神戸倉庫", "snapshot_time": "16:00"}],
        },
    ).json()
    candidate = (
        tmp_path / "FormalInventory" / handoff["handoff_id"]
        / handoff["files"][0]["candidate_file"]
    )
    candidate.write_bytes(candidate.read_bytes() + b"modified")

    response = client.get(f"/api/formal-inventory/{handoff['handoff_id']}/pipeline")

    assert response.status_code == 404
    assert "整合性" in response.json()["detail"]


def test_approved_inventory_builds_formal_daily_history_and_forecast(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    approved = approved_formal_pipeline(client, pilot_forecast_zip())
    registration_id = approved["registration_id"]

    view = client.get(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast"
    )
    assert view.status_code == 200, view.text
    assert view.json()["inventory_status"] == "APPROVED"
    assert len(view.json()["identity_proposal"]) == 10
    assert view.json()["identity_proposal"][0]["canonical_product_id"] == _jan13(0)

    response = client.post(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast",
        json={
            "actor": "予測確認者",
            "reason": "JAN対応と日次ファイル内の出荷0を確認",
            "confirm_identity_bridge": True,
            "confirm_zero_policy": True,
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "FORECAST_COMPLETED"
    assert result["eligible_series_count"] == 10
    assert result["blocked_series_count"] == 0
    assert result["horizon_days"] == 14
    assert len(result["predictions"]) == 140
    assert result["predictions"][0]["current_inventory_cases"] is not None
    assert (tmp_path / "FormalForecast" / result["build_id"] / "daily.csv").is_file()
    assert client.get(
        f"/api/formal-forecast/{result['build_id']}/download"
    ).status_code == 200

    restarted = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    persisted = restarted.get(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast"
    ).json()["latest"]
    assert persisted["build_id"] == result["build_id"]
    repeated = restarted.post(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast",
        json={
            "actor": "予測確認者",
            "reason": "JAN対応と日次ファイル内の出荷0を確認",
            "confirm_identity_bridge": True,
            "confirm_zero_policy": True,
        },
    ).json()
    assert repeated["build_id"] == result["build_id"]
    assert repeated["prediction_sha256"] == result["prediction_sha256"]
    prediction_path = (
        tmp_path / "FormalForecast" / result["build_id"] / "predictions.json"
    )
    prediction_path.write_bytes(prediction_path.read_bytes() + b"modified")
    assert restarted.get(
        f"/api/formal-forecast/{result['build_id']}/download"
    ).status_code == 404


def test_formal_build_is_queued_once_in_existing_production_contracts(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert client.get("/production.js").status_code == 200
    assert 'id="production-run"' in client.get("/").text
    registration_id = approved_formal_pipeline(
        client, pilot_forecast_zip()
    )["registration_id"]
    forecast_result = client.post(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast",
        json={
            "actor": "予測確認者", "reason": "正式予測条件を確認",
            "confirm_identity_bridge": True, "confirm_zero_policy": True,
        },
    ).json()
    build_id = forecast_result["build_id"]

    queued = client.post(
        f"/api/formal-forecast/{build_id}/production-run",
        json={
            "actor": "運用管理者", "reason": "日次Runへ登録",
            "confirm_production_queue": True,
        },
    )

    assert queued.status_code == 202, queued.text
    receipt = queued.json()
    assert receipt["run_status"] in {"QUEUED", "RUNNING", "SUCCEEDED"}
    assert receipt["provider_id"] == "builtin-baseline"
    assert receipt["runtime_version"] == "builtin-baseline-v1"
    assert receipt["runtime_configuration_sha256"]
    assert {item["status"] for item in receipt["runtime_resolutions"]} == {
        "BASELINE_SELECTED"
    }
    assert len(receipt["eligible_series"]) == 10
    assert receipt["blocked_series"] == []
    repeated = client.post(
        f"/api/formal-forecast/{build_id}/production-run",
        json={
            "actor": "別の再送者", "reason": "誤って再送",
            "confirm_production_queue": True,
        },
    ).json()
    assert repeated["run_id"] == receipt["run_id"]
    deadline = time.monotonic() + 5
    while True:
        view = client.get(f"/api/formal-forecast/{build_id}/production-run").json()
        if view["handoff"]["run_status"] == "SUCCEEDED" or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    assert view["queued"] is True
    assert view["handoff"]["run_id"] == receipt["run_id"]
    assert view["handoff"]["run_status"] == "SUCCEEDED"
    assert len(view["handoff"]["point_predictions"]) == 140

    restarted = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    restored = restarted.get(
        f"/api/formal-forecast/{build_id}/production-run"
    ).json()["handoff"]
    assert restored["run_status"] == "SUCCEEDED"
    assert restored["run_id"] == receipt["run_id"]

    projection = restarted.get(
        f"/api/formal-forecast/{build_id}/production-projection"
    )
    assert projection.status_code == 200, projection.text
    assert len(projection.json()["projections"]) == 10


def test_multi_warehouse_daily_summary_is_auditable_and_idempotent(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert 'id="daily-summary"' in client.get("/").text
    registration_id = approved_multi_center_pipeline(client)["registration_id"]
    forecast = client.post(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast",
        json={
            "actor": "予測確認者", "reason": "2倉庫の予測条件を確認",
            "confirm_identity_bridge": True, "confirm_zero_policy": True,
        },
    ).json()
    build_id = forecast["build_id"]
    queued = client.post(
        f"/api/formal-forecast/{build_id}/production-run",
        json={
            "actor": "運用管理者", "reason": "2倉庫の日次Runへ登録",
            "confirm_production_queue": True,
        },
    )
    assert queued.status_code == 202, queued.text
    deadline = time.monotonic() + 8
    while True:
        run = client.get(f"/api/formal-forecast/{build_id}/production-run").json()
        if run["handoff"]["run_status"] == "SUCCEEDED" or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    assert run["handoff"]["run_status"] == "SUCCEEDED"

    projection = client.get(
        f"/api/formal-forecast/{build_id}/production-projection"
    )
    assert projection.status_code == 200, projection.text
    assert projection.json()["status"] == "READY"
    assert len(projection.json()["scope_results"]) == 2
    assert len(projection.json()["projections"]) == 20

    policy = {
        "actor": "現場責任者", "reason": "初回の賞味期限確認条件",
        "minimum_remaining_days": 0, "attention_days": 7,
        "confirm_expiry_policy": True,
    }
    response = client.post(
        f"/api/formal-forecast/{build_id}/daily-summary", json=policy,
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "READY"
    assert result["mode"] == "SHADOW"
    assert len(result["warehouses"]) == 2
    assert len(result["rows"]) == 20
    assert result["blockers"] == []
    assert result["replenishment_policy_status"].startswith("NOT_CALCULATED")
    assert any(item["replenishment_candidate"] for item in result["rows"])
    assert any("EXPIRY_RISK" in item["risk_flags"] for item in result["rows"])

    restarted = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    repeated = restarted.post(
        f"/api/formal-forecast/{build_id}/daily-summary", json=policy,
    ).json()
    assert repeated == result
    target = (
        tmp_path / "FormalForecast" / "ProductionSummaries"
        / f"{result['request_key']}.json"
    )
    target.write_bytes(target.read_bytes() + b"modified")
    tampered = restarted.post(
        f"/api/formal-forecast/{build_id}/daily-summary", json=policy,
    )
    assert tampered.status_code == 422
    assert "整合性" in tampered.json()["detail"]


def test_daily_summary_builds_arrival_time_shipment_recommendations(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert 'id="shipment-decision"' in client.get("/").text
    assert client.get("/shipment-decision.js").status_code == 200
    registration_id = approved_multi_center_pipeline(client)["registration_id"]
    forecast = client.post(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast",
        json={
            "actor": "予測確認者", "reason": "2倉庫の予測条件を確認",
            "confirm_identity_bridge": True, "confirm_zero_policy": True,
        },
    ).json()
    build_id = forecast["build_id"]
    client.post(
        f"/api/formal-forecast/{build_id}/production-run",
        json={
            "actor": "運用管理者", "reason": "2倉庫の日次Runへ登録",
            "confirm_production_queue": True,
        },
    )
    deadline = time.monotonic() + 8
    while True:
        run = client.get(f"/api/formal-forecast/{build_id}/production-run").json()
        if run["handoff"]["run_status"] == "SUCCEEDED" or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    summary = client.post(
        f"/api/formal-forecast/{build_id}/daily-summary",
        json={
            "actor": "現場責任者", "reason": "賞味期限条件を確認",
            "minimum_remaining_days": 0, "attention_days": 7,
            "confirm_expiry_policy": True,
        },
    ).json()
    warehouses = [item["warehouse_id"] for item in summary["warehouses"]]
    jans = sorted({item["jan"] for item in summary["rows"]})
    request = {
        "actor": "出荷責任者", "reason": "工場在庫と運用policyを確認",
        "confirm_decision_inputs": True,
        "routes": [
            {
                "policy_id": f"route-v1-{warehouse}",
                "policy_version": f"route-v1-{warehouse}",
                "location_master_version": "locations-v1",
                "factory_location_id": "F01", "warehouse_location_id": warehouse,
                "minimum_hours": 12, "standard_hours": 24, "maximum_hours": 36,
                "recommendation_basis": "MAXIMUM",
                "effective_from": "2026-01-01", "effective_to": None,
            }
            for warehouse in warehouses
        ],
        "safety_stock_policies": [
            {
                "policy_version": f"safety-v1-{warehouse}",
                "warehouse_id": warehouse, "coverage_days": 3,
                "shipment_unit_cases": "1",
            }
            for warehouse in warehouses
        ],
        "factory_supplies": [
            {
                "snapshot_id": "factory-snapshot-v1",
                "snapshot_at": "2026-01-01T00:00:00+00:00",
                "factory_id": "F01", "jan": jan, "inventory_cases": "1000",
            }
            for jan in jans
        ],
        "production_plans": [],
    }
    endpoint = (
        f"/api/formal-forecast/{build_id}/daily-summary/"
        f"{summary['request_key']}/shipment-recommendation"
    )

    response = client.post(endpoint, json=request)

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["mode"] == "SHADOW"
    assert len(result["recommendations"]) == 20
    assert result["blockers"] == []
    assert result["input_versions"]["factory_snapshot_ids"] == ["factory-snapshot-v1"]
    assert any(Decimal(item["recommended_shipment_cases"]) > 0
               for item in result["recommendations"])
    restarted = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert restarted.post(endpoint, json=request).json() == result
    target = tmp_path / "FormalForecast" / "ProductionDecisions" / f"{result['request_key']}.json"
    target.write_bytes(target.read_bytes() + b"modified")
    tampered = restarted.post(endpoint, json=request)
    assert tampered.status_code == 422
    assert "整合性" in tampered.json()["detail"]


def test_production_handoff_preserves_blocked_series_and_rejects_tampering(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    registration_id = approved_formal_pipeline(
        client, pilot_forecast_zip(invalid_recent=True)
    )["registration_id"]
    result = client.post(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast",
        json={
            "actor": "予測確認者", "reason": "欠測を隔離",
            "confirm_identity_bridge": True, "confirm_zero_policy": True,
        },
    ).json()
    build_id = result["build_id"]
    queued = client.post(
        f"/api/formal-forecast/{build_id}/production-run",
        json={
            "actor": "運用管理者", "reason": "対象内だけ登録",
            "confirm_production_queue": True,
        },
    ).json()
    assert len(queued["eligible_series"]) == 9
    assert len(queued["blocked_series"]) == 1

    receipt = tmp_path / "FormalForecast" / "ProductionHandoffs" / f"{build_id}.json"
    receipt.write_bytes(receipt.read_bytes() + b"modified")
    response = client.get(f"/api/formal-forecast/{build_id}/production-run")
    assert response.status_code == 404
    assert "整合性" in response.json()["detail"]


def test_formal_forecast_requires_explicit_identity_and_zero_policy(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    registration_id = approved_formal_pipeline(
        client, pilot_forecast_zip()
    )["registration_id"]

    response = client.post(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast",
        json={
            "actor": "予測確認者",
            "reason": "未確認条件の拒否を確認",
            "confirm_identity_bridge": True,
            "confirm_zero_policy": False,
        },
    )

    assert response.status_code == 422
    assert "出荷0日" in response.json()["detail"]
    assert not list((tmp_path / "FormalForecast").glob("portable-daily-*"))


def test_formal_forecast_keeps_invalid_product_blocked_and_runs_others(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    registration_id = approved_formal_pipeline(
        client, pilot_forecast_zip(invalid_recent=True)
    )["registration_id"]

    response = client.post(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast",
        json={
            "actor": "予測確認者",
            "reason": "不正行を0へ変換しないことを確認",
            "confirm_identity_bridge": True,
            "confirm_zero_policy": True,
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "FORECAST_COMPLETED_WITH_BLOCKERS"
    assert result["eligible_series_count"] == 9
    assert result["blocked_series_count"] == 1
    blocked = next(item for item in result["series"] if not item["forecast_eligible"])
    assert blocked["jan"] == _jan13(0)
    assert blocked["blocking_reasons"] == ["RECENT_SOURCE_DAYS_MISSING"]
    assert len(result["predictions"]) == 126


def test_formal_daily_uses_each_center_origin_and_blocks_inventory_date_mismatch(
    tmp_path: Path,
):
    raw_target = io.BytesIO()
    prepared_rows = ["ds,unique_id,y"]
    centers = (
        ("加須", "KAZO", _jan13(0), date(2026, 2, 4)),
        ("神戸", "KOBE", _jan13(1), date(2026, 1, 31)),
    )
    with zipfile.ZipFile(raw_target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source_center, _center_id, jan, origin in centers:
            for offset in range(35):
                day = origin - timedelta(days=34 - offset)
                rows = (
                    "出荷日,納品日,商品名,JAN,数量\n"
                    f"{day:%Y/%m/%d},{day:%Y/%m/%d},正式商品,{jan},1\n"
                )
                archive.writestr(
                    f"data/{source_center}日時出荷_{day:%Y%m%d}.csv",
                    rows.encode("cp932"),
                )
                prepared_rows.append(f"{day},{source_center}:{jan},1")
    archive_path = tmp_path / "input.zip"
    archive_path.write_bytes(raw_target.getvalue())
    prepared_path = tmp_path / "prepared.csv"
    prepared_path.write_text("\n".join(prepared_rows) + "\n", encoding="utf-8")
    identities = [
        {
            "source_center": source_center,
            "jan": jan,
            "canonical_product_id": jan,
            "forecast_center_id": center_id,
        }
        for source_center, center_id, jan, _origin in centers
    ]

    build, frame = build_daily_shipment(
        archive_path=archive_path,
        prepared_path=prepared_path,
        handoff={"source_archive_sha256": hashlib.sha256(raw_target.getvalue()).hexdigest()},
        registration_id="registration",
        identities=identities,
        zero_when_file_present=True,
        snapshot_dates_by_center={"加須": date(2026, 2, 4), "神戸": date(2026, 2, 4)},
    )

    assert build["center_windows"] == [
        {
            "source_center": "加須",
            "train_start": "2026-01-01",
            "train_end": "2026-02-04",
            "inventory_snapshot_date": "2026-02-04",
        },
        {
            "source_center": "神戸",
            "train_start": "2025-12-28",
            "train_end": "2026-01-31",
            "inventory_snapshot_date": "2026-02-04",
        },
    ]
    summaries = {item["source_center"]: item for item in build["series"]}
    assert summaries["加須"]["forecast_eligible"] is True
    assert summaries["神戸"]["blocking_reasons"] == [
        "INVENTORY_SHIPMENT_AS_OF_MISMATCH"
    ]
    assert set(frame["source_center"]) == {"加須"}
    assert frame["ds"].max().date() == date(2026, 2, 4)


def test_end_to_end_and_restart(tmp_path: Path):
    data = (
        Path(__file__).resolve().parents[2] / "portable" / "sample" / "synthetic_shipments.csv"
    ).read_bytes()
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert client.get("/api/sample.csv").content == data
    first = client.post("/api/runs", content=data, headers={"Content-Type": "text/csv"})
    assert first.status_code == 201, first.text
    result = first.json()
    assert result["status"] == "SUCCESS"
    assert result["input_sha256"] == hashlib.sha256(data).hexdigest()
    assert len(result["predictions"]) == 14
    assert (tmp_path / "Results" / f"{result['run_id']}.json").is_file()
    assert client.get(f"/api/runs/{result['run_id']}/download").status_code == 200

    restarted = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    history = restarted.get("/api/runs").json()
    assert history[0]["run_id"] == result["run_id"]
    again = restarted.post("/api/runs", content=data, headers={"Content-Type": "text/csv"})
    assert again.status_code == 201, again.text
    assert again.json()["input_sha256"] == result["input_sha256"]
    assert again.json()["result_sha256"] == result["result_sha256"]
    assert again.json()["predictions"] == result["predictions"]


def test_interrupted_run_is_not_success(tmp_path: Path):
    store = RunStore(tmp_path / "runs.sqlite3")
    store.start("interrupted", "hash", "v1", "baseline")
    reopened = RunStore(tmp_path / "runs.sqlite3")
    assert reopened.get("interrupted")["status"] == "INTERRUPTED"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"junk\n",
        b"ds,unique_id,y\n2026-01-01,A,-1\n",
        b"ds,unique_id,y\n2026-01-01,A,1\n2026-01-01,A,2\n",
    ],
)
def test_invalid_csv_is_rejected_without_success(tmp_path: Path, data: bytes):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    response = client.post("/api/runs", content=data, headers={"Content-Type": "text/csv"})
    assert response.status_code == 422
    assert client.get("/api/runs").json()[0]["status"] == "FAILED"


def test_local_boundary_and_result_integrity(tmp_path: Path):
    client = TestClient(create_app(tmp_path, control_token="secret"), base_url="http://127.0.0.1")
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
    assert (
        client.post(
            "/api/runs",
            content=synthetic_csv(),
            headers={"Content-Type": "text/csv", "Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert client.post("/api/control/drain").status_code == 403
    result = client.post(
        "/api/runs", content=synthetic_csv(), headers={"Content-Type": "text/csv"}
    ).json()
    path = tmp_path / "Results" / f"{result['run_id']}.json"
    path.write_text(json.dumps([{"tampered": True}]), encoding="utf-8")
    assert client.get(f"/api/runs/{result['run_id']}").status_code == 500
    assert client.post("/api/control/drain", headers={"X-Portable-Control": "secret"}).json() == {
        "active": 0
    }
    assert (
        client.post(
            "/api/runs", content=synthetic_csv(), headers={"Content-Type": "text/csv"}
        ).status_code
        == 503
    )


def test_port_collision_selects_next_port():
    import socket

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 48150))
        assert next(available_ports()) != 48150


def test_mutex_prevents_double_start_and_recovers(tmp_path: Path):
    with SingleInstance(tmp_path):
        with pytest.raises(AlreadyRunning):
            with SingleInstance(tmp_path):
                pass
    with SingleInstance(tmp_path):
        pass


def test_unwritable_data_root_fails_early(tmp_path: Path):
    (tmp_path / "State").write_text("blocks a directory", encoding="utf-8")
    with pytest.raises(OSError):
        DataPaths(tmp_path).ensure()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object only")
def test_supervised_source_server_starts_and_stops(tmp_path: Path):
    paths = DataPaths(tmp_path)
    paths.ensure()
    job = ChildJob()
    token = secrets.token_urlsafe(24)
    try:
        child, port = start_server(paths, job, token)
        assert request_json(port, "/ready")["ready"]
        assert child.poll() is None
        stop_server(child, port, token)
        assert child.poll() is not None
    finally:
        job.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object only")
def test_launcher_crash_kills_api_and_releases_mutex(tmp_path: Path):
    import ctypes

    helper = Path(__file__).with_name("crash_helper.py")
    process = subprocess.Popen(
        [sys.executable, str(helper), str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        marker = tmp_path / "child.pid"
        for _ in range(150):
            if marker.is_file():
                break
            if process.poll() is not None:
                raise AssertionError("helper exited before API was ready")
            time.sleep(0.1)
        else:
            raise AssertionError("API never became ready")
        pid = int(marker.read_text(encoding="ascii").split(",")[0])
        process.kill()
        process.wait(timeout=5)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 10_000) == 0
            finally:
                kernel.CloseHandle(handle)
        with SingleInstance(tmp_path):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_formal_decision_input_zip_is_validated_and_connected(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert 'id="decision-package-form"' in client.get("/").text
    assert 'id="decision-review-form"' in client.get("/").text
    assert 'id="decision-outcome-form"' in client.get("/").text
    assert client.get("/shipment-review.js").status_code == 200
    assert client.get("/shipment-outcomes.js").status_code == 200
    registration_id = approved_multi_center_pipeline(client)["registration_id"]
    forecast = client.post(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast",
        json={
            "actor": "予測確認者", "reason": "2倉庫の予測条件を確認",
            "confirm_identity_bridge": True, "confirm_zero_policy": True,
        },
    ).json()
    build_id = forecast["build_id"]
    client.post(
        f"/api/formal-forecast/{build_id}/production-run",
        json={
            "actor": "運用管理者", "reason": "2倉庫の日次Runへ登録",
            "confirm_production_queue": True,
        },
    )
    deadline = time.monotonic() + 8
    while True:
        run = client.get(f"/api/formal-forecast/{build_id}/production-run").json()
        if run["handoff"]["run_status"] == "SUCCEEDED" or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    summary = client.post(
        f"/api/formal-forecast/{build_id}/daily-summary",
        json={
            "actor": "現場責任者", "reason": "賞味期限条件を確認",
            "minimum_remaining_days": 0, "attention_days": 7,
            "confirm_expiry_policy": True,
        },
    ).json()
    endpoint = f"/api/formal-forecast/{build_id}/daily-summary/{summary['request_key']}"
    template = client.get(f"{endpoint}/decision-input-template")
    assert template.status_code == 200
    assert template.headers["content-type"] == "application/zip"
    warehouses = [item["warehouse_id"] for item in summary["warehouses"]]
    jans = sorted({item["jan"] for item in summary["rows"]})
    calculation_date = summary["calculation_at"][:10]
    files = {
        "factory_inventory.csv": (
            "factory_snapshot_id,snapshot_at,factory_id,jan,inventory_cases\n"
            + "".join(
                f"factory-v1,2026-01-01T00:00:00+00:00,F01,{jan},1000\n"
                for jan in jans
            )
        ),
        "production_plans.csv": (
            "plan_id,plan_version,factory_id,jan,completion_at,quantity_cases\n"
        ),
        "routes.csv": (
            "policy_id,policy_version,location_master_version,factory_location_id,"
            "warehouse_location_id,minimum_hours,standard_hours,maximum_hours,"
            "recommendation_basis,effective_from,effective_to\n"
            + "".join(
                f"route-{warehouse},routes-v1,locations-v1,F01,{warehouse},"
                f"12,24,36,MAXIMUM,{calculation_date},\n"
                for warehouse in warehouses
            )
        ),
        "safety_stock.csv": (
            "policy_version,warehouse_id,coverage_days,shipment_unit_cases\n"
            + "".join(f"safety-v1,{warehouse},3,1\n" for warehouse in warehouses)
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8-sig"))
    package_request = {
        "actor": "出荷責任者", "reason": "正式CSV入力を確認",
        "confirm_decision_inputs": True,
        "archive_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
    }

    package_response = client.post(f"{endpoint}/decision-inputs", json=package_request)

    assert package_response.status_code == 201, package_response.text
    package = package_response.json()
    assert package["status"] == "READY"
    assert package["ready_for_decision"] is True
    assert package["quarantines"] == []
    repeated = client.post(f"{endpoint}/decision-inputs", json=package_request).json()
    assert repeated == package
    result_response = client.post(
        f"{endpoint}/shipment-recommendation",
        json={
            "decision_input_package_id": package["package_id"],
            "confirm_decision_inputs": True,
        },
    )
    assert result_response.status_code == 201, result_response.text
    result = result_response.json()
    assert len(result["recommendations"]) == 20
    assert result["input_versions"]["decision_input_package_id"] == package["package_id"]
    recommendation = result["recommendations"][0]
    review_endpoint = (
        f"{endpoint}/shipment-recommendation/{result['request_key']}/review"
    )
    review_request = {
        "jan": recommendation["jan"],
        "warehouse_id": recommendation["warehouse_id"],
        "expected_revision": 0,
        "operator_decision": "ACCEPTED",
        "operator_quantity_cases": recommendation["recommended_shipment_cases"],
        "reason_code": None,
        "comment": None,
        "actor": "現場担当者",
        "confirm_shadow_review": True,
    }
    review_response = client.post(review_endpoint, json=review_request)
    assert review_response.status_code == 201, review_response.text
    review = review_response.json()
    assert review["latest"][
        f"{recommendation['jan']}::{recommendation['warehouse_id']}"
    ]["operator_decision"] == "ACCEPTED"
    assert client.post(review_endpoint, json=review_request).json() == review
    assert client.get(review_endpoint).json() == review
    changed_review = {
        **review_request,
        "expected_revision": 1,
        "operator_decision": "INCREASED",
        "operator_quantity_cases": str(
            Decimal(recommendation["recommended_shipment_cases"]) + 1
        ),
        "reason_code": "EXPECTED_LARGE_ORDER",
    }
    changed_response = client.post(review_endpoint, json=changed_review)
    assert changed_response.status_code == 201, changed_response.text
    assert changed_response.json()["improvement_candidates"][0]["count"] == 1
    outcome_endpoint = (
        f"{endpoint}/shipment-recommendation/{result['request_key']}/outcomes"
    )
    empty_outcomes = client.get(outcome_endpoint).json()
    assert empty_outcomes["actual_count"] == 0
    assert empty_outcomes["business_kpis"]["stockout_cases"] is None
    template_response = client.get(f"{outcome_endpoint}/template")
    reader = csv.DictReader(
        io.StringIO(template_response.content.decode("utf-8-sig"), newline="")
    )
    rows = list(reader)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=reader.fieldnames, lineterminator="\r\n")
    writer.writeheader()
    for index, row in enumerate(rows):
        row["actual_shipped_quantity"] = "0"
        if index == 0:
            row.update({
                "actual_demand_quantity": "4", "stockout_quantity": "0",
                "expired_quantity": "", "interwarehouse_transfer_quantity": "0",
            })
        writer.writerow(row)
    outcome_request = {
        "source_version": "field-result-v1",
        "known_at": datetime.now().astimezone().isoformat(),
        "confirm_actual_outcomes": True,
        "csv_base64": base64.b64encode(
            output.getvalue().encode("utf-8-sig")
        ).decode("ascii"),
    }
    outcome_response = client.post(outcome_endpoint, json=outcome_request)
    assert outcome_response.status_code == 201, outcome_response.text
    outcome = outcome_response.json()
    assert outcome["actual_count"] == len(rows) == 20
    assert outcome["business_kpis"]["stockout_cases"] == "0"
    assert outcome["business_kpis"]["expired_cases"] is None
    assert outcome["kpi_coverage"]["stockout_cases"] == 1
    assert outcome["kpi_coverage"]["expired_cases"] == 0
    assert outcome["rows"][0]["actual_shipped_cases"] == "0"
    assert client.post(outcome_endpoint, json=outcome_request).json() == outcome
    assert client.get(outcome_endpoint).json() == outcome
    learning_overview = client.get("/api/learning-reviews").json()
    assert learning_overview["available_pilot_scope_versions"]
    assert client.get("/learning-reviews.js").status_code == 200
    assert 'id="learning-review-form"' in client.get("/").text
    weekly_request = {
        "week_end": result["calculation_at"][:10],
        "pilot_scope_versions": learning_overview["available_pilot_scope_versions"],
        "aggregation_version": "portable-weekly-v1",
        "threshold_version": "field-threshold-v1",
        "minimum_evidence_count": 1,
        "reviewer": "現場責任者",
        "known_at": datetime.now().astimezone().isoformat(),
        "confirm_shadow_review": True,
    }
    weekly_response = client.post("/api/learning-reviews", json=weekly_request)
    assert weekly_response.status_code == 201, weekly_response.text
    weekly = weekly_response.json()
    assert weekly["report"]["current"]["comparison_coverage"]["actual_any"] == 20
    assert weekly["report"]["current"]["operational_kpis"]["expired_cases"] is None
    large_order = next(
        item for item in weekly["candidates"]
        if item["candidate_type"] == "LARGE_ORDER_INPUT"
    )
    decision_request = {
        "expected_revision": 0,
        "decision": "APPROVED",
        "subject": "現場責任者",
        "reason": "大口予定の取得方法を調査",
        "confirm_no_automatic_application": True,
    }
    candidate_endpoint = (
        f"/api/learning-candidates/{large_order['candidate_id']}/decision"
    )
    approved = client.post(candidate_endpoint, json=decision_request)
    assert approved.status_code == 201, approved.text
    approved_candidate = next(
        item for item in approved.json()["candidates"]
        if item["candidate_id"] == large_order["candidate_id"]
    )
    assert approved_candidate["status"] == "APPROVED"
    assert client.post(candidate_endpoint, json=decision_request).json() == approved.json()
    repeated_weekly = client.post("/api/learning-reviews", json=weekly_request).json()
    assert repeated_weekly["review_id"] == weekly["review_id"]
    assert repeated_weekly["content_sha256"] == weekly["content_sha256"]
    assert repeated_weekly["candidates"][0]["status"] == "APPROVED"
    stored = (
        tmp_path / "FormalForecast" / "DecisionInputs" / f"{package['package_id']}.json"
    )
    stored.write_bytes(stored.read_bytes() + b"modified")
    tampered = client.post(
        f"{endpoint}/shipment-recommendation",
        json={
            "decision_input_package_id": package["package_id"],
            "confirm_decision_inputs": True,
        },
    )
    assert tampered.status_code == 422
    assert "整合性" in tampered.json()["detail"]
