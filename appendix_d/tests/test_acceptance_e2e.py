"""受入API、別process Worker、業務判断のPhase 1K結合試験。"""

import hashlib
import subprocess
import sys
from pathlib import Path

from acceptance_support import acceptance_payload, build_three_product_daily
from fastapi.testclient import TestClient

from forecast_provider.acceptance import SqliteAcceptanceStore
from forecast_provider.acceptance.checks import evaluate_acceptance
from forecast_provider.acceptance.report import publish_report
from forecast_provider.api import create_app
from forecast_provider.jobs import SqliteRunStore


def test_anonymized_case_is_dry_run_and_cannot_be_approved(tmp_path):
    database = tmp_path / "kiban.sqlite3"
    daily, catalog, products, build = build_three_product_daily(tmp_path, database)
    acceptance = SqliteAcceptanceStore(database)
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            catalog,
            "token",
            daily=daily,
            acceptance=acceptance,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    created = api.post(
        "/api/acceptance-cases",
        json=acceptance_payload(build.build_id, products),
    )
    assert created.status_code == 202
    report_root = tmp_path / "reports"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "forecast_provider.acceptance_worker",
            "--sqlite",
            str(database),
            "--output-root",
            str(report_root),
            "--once",
        ],
        check=True,
    )
    case_id = created.json()["id"]
    result = api.get(f"/api/acceptance-cases/{case_id}").json()
    assert result["status"] == "SUCCEEDED"
    assert result["outcome"] == "DRY_RUN"
    listed = api.get("/api/acceptance-cases")
    assert listed.status_code == 200
    assert [item["case_id"] for item in listed.json()] == [case_id]
    checks = api.get(f"/api/acceptance-cases/{case_id}/checks").json()
    assert len(checks) == 10
    assert [item for item in checks if item["status"] == "NOT_EVALUATED"] == [
        next(item for item in checks if item["check_id"] == "REAL_DATA_DECLARATION")
    ]
    for key in ("report_uri", "markdown_uri"):
        path = Path(result[key].replace("file:///", ""))
        assert path.exists()
        checksum_key = "report_sha256" if key == "report_uri" else "markdown_sha256"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == result[checksum_key]
    case = acceptance.get_case(case_id)
    rebuilt_checks, summary, outcome = evaluate_acceptance(case, daily, catalog)
    rebuilt = publish_report(case, rebuilt_checks, summary, outcome, tmp_path / "rebuilt")
    assert rebuilt[1] == result["report_sha256"]
    assert rebuilt[3] == result["markdown_sha256"]
    approval = api.post(
        f"/api/acceptance-cases/{case_id}/decisions",
        json={
            "decision_version": "decision-v1",
            "decision": "APPROVED",
            "decided_by": "owner@example.test",
            "reason": "匿名fixture",
        },
    )
    assert approval.status_code == 409
    rejection = api.post(
        f"/api/acceptance-cases/{case_id}/decisions",
        json={
            "decision_version": "decision-v1",
            "decision": "REJECTED",
            "decided_by": "owner@example.test",
            "reason": "実データではないため",
        },
    )
    assert rejection.status_code == 201
    assert api.get(f"/api/acceptance-cases/{case_id}/decisions").json()[0]["reason"]


def test_real_case_with_passing_evidence_can_be_approved(tmp_path):
    from forecast_provider.acceptance import (
        AcceptanceProcessor,
        make_acceptance_case,
        make_acceptance_decision,
    )

    database = tmp_path / "real-contract.sqlite3"
    daily, catalog, products, build = build_three_product_daily(tmp_path, database)
    store = SqliteAcceptanceStore(database)
    case = make_acceptance_case(acceptance_payload(build.build_id, products, "REAL"))
    store.put_case(case)
    result = AcceptanceProcessor(store, daily, catalog, tmp_path / "reports").process_next()
    assert result.outcome == "PASSED"
    decision = make_acceptance_decision(
        case.case_id,
        "decision-v1",
        "APPROVED",
        "owner@example.test",
        "技術証跡を確認",
    )
    store.put_decision(decision)
    assert store.list_decisions(case.case_id) == [decision]


def test_daily_ledger_change_is_detected_against_published_csv(tmp_path):
    import sqlite3

    from forecast_provider.acceptance import AcceptanceProcessor, make_acceptance_case

    database = tmp_path / "tampered.sqlite3"
    daily, catalog, products, build = build_three_product_daily(tmp_path, database)
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE daily_values SET y='999' WHERE build_id=? AND ds='2026-01-01'",
            (build.build_id,),
        )
    store = SqliteAcceptanceStore(database)
    case = make_acceptance_case(acceptance_payload(build.build_id, products))
    store.put_case(case)
    result = AcceptanceProcessor(store, daily, catalog, tmp_path / "reports").process_next()
    assert result.outcome == "FAILED"
    checksum = next(
        item for item in store.list_checks(case.case_id) if item.check_id == "ARTIFACT_CHECKSUM"
    )
    assert checksum.status == "FAILED"
    assert "日次台帳とCSV" in checksum.actual["detail"]
