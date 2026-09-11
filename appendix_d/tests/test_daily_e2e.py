"""API・別process Worker・snapshotのPhase 1J結合試験。"""

import hashlib
import subprocess
import sys

import pandas as pd
from daily_support import HEADER, build_payload, create_master, normalize_files, schedule_payload
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.catalog.domain import make_snapshot
from forecast_provider.daily import SqliteDailyStore, make_daily_build, make_file_schedule
from forecast_provider.daily.snapshot import snapshot_manifest
from forecast_provider.executors.builtin_baseline import _read_snapshot
from forecast_provider.jobs import SqliteRunStore


def test_api_to_separate_daily_worker_emits_all_states_and_snapshot(tmp_path):
    database = tmp_path / "kiban.sqlite3"
    jobs = normalize_files(
        tmp_path,
        database,
        {
            "day1.csv": HEADER + "2026-01-01,001,日次商品,4,PACK,C1,SHIPMENT\n",
            "day2.csv": HEADER,
            "day3.csv": HEADER + "\n",
            "day4.csv": HEADER + "2026-01-04,001,日次商品,-1,PACK,C1,SHIPMENT\n",
            "day5.csv": HEADER + "\n\n",
        },
    )
    master, product = create_master(database)
    catalog = SqliteCatalogStore(database)
    daily = SqliteDailyStore(database)
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            catalog,
            "token",
            master=master,
            daily=daily,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    schedule = api.post("/api/file-schedules", json=schedule_payload())
    assert schedule.status_code == 201
    closure = api.post(
        "/api/closed-days",
        json={
            "center_id": "C1",
            "closed_date": "2026-01-05",
            "closure_version": "closure-v1",
            "available_at": "2025-12-01T00:00:00+09:00",
            "approved_by": "operator@example.test",
            "reason": "休業表を確認",
        },
    )
    assert closure.status_code == 201
    payload = build_payload(
        schedule.json()["id"],
        [job.normalization_id for job in jobs],
        product.canonical_product_id,
    )
    created = api.post("/api/daily-builds", json=payload)
    assert created.status_code == 202
    output_root = tmp_path / "snapshots"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "forecast_provider.daily_worker",
            "--sqlite",
            str(database),
            "--output-root",
            str(output_root),
            "--once",
        ],
        check=True,
    )
    build_id = created.json()["id"]
    result = api.get(f"/api/daily-builds/{build_id}")
    assert result.status_code == 200
    assert result.json()["status"] == "SUCCEEDED"
    rows = api.get(f"/api/daily-builds/{build_id}/values").json()
    assert [row["state"] for row in rows] == [
        "OBSERVED",
        "CONFIRMED_ZERO",
        "MISSING",
        "PARTIAL_OR_INVALID",
        "CLOSED",
        "NOT_HANDLED",
    ]
    assert rows[0]["y"] == 4
    assert rows[1]["y"] == 0
    assert rows[2]["y"] is None
    assert rows[4]["y"] == 0
    assert rows[4]["available_at"] == "2025-11-30T15:00:00+00:00"
    builds = api.get("/api/daily-builds").json()
    assert builds[0]["build_id"] == build_id
    readiness = api.get(f"/api/daily-builds/{build_id}/readiness").json()
    assert readiness["value_count"] == 6
    assert readiness["state_counts"] == {
        "CLOSED": 1,
        "CONFIRMED_ZERO": 1,
        "MISSING": 1,
        "NOT_HANDLED": 1,
        "OBSERVED": 1,
        "PARTIAL_OR_INVALID": 1,
    }
    missing = api.get(f"/api/daily-builds/{build_id}/value-page", params={"state": "MISSING"})
    assert missing.status_code == 200
    assert missing.json()["total"] == 1
    assert missing.json()["items"][0]["state"] == "MISSING"
    assert (
        api.get(f"/api/daily-builds/{build_id}/value-page", params={"state": "INVALID"}).status_code
        == 422
    )
    completeness = api.get(f"/api/daily-builds/{build_id}/completeness").json()
    assert completeness[2]["status"] == "COMPLETE"
    assert completeness[2]["zero_confirmable"] is False
    assert completeness[3]["status"] == "PARTIAL_OR_INVALID"
    assert completeness[5]["expected_count"] == 0
    snapshot = catalog.get_snapshot(result.json()["snapshot_id"])
    assert snapshot.manifest["provenance"]["daily_build_id"] == build_id
    csv_path = next((output_root / "daily").glob("*.csv"))
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == result.json()["data_sha256"]
    frame = pd.read_csv(csv_path)
    assert frame.daily_state.tolist() == [row["state"] for row in rows]
    rebuilt = make_snapshot(
        snapshot_manifest(
            make_daily_build(payload),
            daily.list_values(build_id),
            result.json()["data_uri"],
            result.json()["data_sha256"],
        )
    )
    assert rebuilt.snapshot_id == snapshot.snapshot_id
    execution_frame, _ = _read_snapshot(snapshot.manifest)
    assert execution_frame.loc[execution_frame.daily_state.eq("CLOSED"), "y"].isna().all()
    assert execution_frame.loc[execution_frame.daily_state.eq("CONFIRMED_ZERO"), "y"].eq(0).all()
    assert make_daily_build(payload).build_id == build_id


def test_unmapped_jan_fails_build_without_snapshot(tmp_path):
    from forecast_provider.daily import DailyProcessor

    database = tmp_path / "unmapped.sqlite3"
    jobs = normalize_files(
        tmp_path,
        database,
        {"day1.csv": HEADER + "2026-01-01,999,不明商品,1,PACK,C1,SHIPMENT\n"},
    )
    _, product = create_master(database)
    payload = schedule_payload()
    payload["files"] = payload["files"][:1]
    schedule = make_file_schedule(payload)
    catalog = SqliteCatalogStore(database)
    daily = SqliteDailyStore(database)
    daily.put_schedule(schedule)
    definition = build_payload(
        schedule.schedule_id, [jobs[0].normalization_id], product.canonical_product_id
    )
    definition["closure_version"] = None
    job = make_daily_build(definition)
    daily.put_job(job)
    result = DailyProcessor(daily, catalog, tmp_path / "output").process_next()
    assert result.status == "FAILED"
    assert "一意に確定しません" in result.error
    assert result.snapshot_id is None
