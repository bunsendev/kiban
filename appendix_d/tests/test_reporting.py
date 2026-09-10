"""比較CSVと採用判断の運用契約。"""

from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient
from test_evaluation_registry import (
    _comparison,
    _completed_run,
    _conformance,
    _experiment,
    _fixture,
)

from forecast_provider.acceptance import (
    SqliteAcceptanceStore,
    make_acceptance_case,
    make_acceptance_decision,
)
from forecast_provider.api import create_app
from forecast_provider.catalog.domain import make_snapshot
from forecast_provider.catalog.files import snapshot_path
from forecast_provider.evaluation_registry import SqliteEvaluationRegistryStore
from forecast_provider.reporting import SqliteReportingStore


def _reporting_fixture(tmp_path):
    _, runs, catalog, data_path, snapshot_id = _fixture(tmp_path)
    acceptance = SqliteAcceptanceStore(runs.path)
    evaluation = SqliteEvaluationRegistryStore(runs.path)
    reporting = SqliteReportingStore(runs.path)
    report_root = tmp_path / "report-output"
    api = TestClient(
        create_app(
            runs,
            catalog,
            "token",
            tmp_path,
            acceptance=acceptance,
            evaluation_registry=evaluation,
            reporting=reporting,
            report_root=report_root,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    return api, runs, catalog, acceptance, report_root, data_path, snapshot_id


def _saved_comparison(api, runs, catalog, snapshot_id, purpose="比較結果CSV"):
    experiment_a, definition_a = _experiment(api, snapshot_id, "moving_average_28")
    experiment_b, definition_b = _experiment(api, snapshot_id, "seasonal_naive_7")
    baseline_run = _completed_run(api, runs, catalog, experiment_a, 9)
    selected_run = _completed_run(api, runs, catalog, experiment_b, 10)
    request = _comparison(
        snapshot_id,
        [baseline_run, selected_run],
        [_conformance(api, definition_a), _conformance(api, definition_b)],
        purpose=purpose,
    )
    response = api.post("/api/comparisons", json=request)
    assert response.status_code == 201, response.text
    return response.json()["comparison_id"], baseline_run, selected_run


def _adoption_payload(comparison_id, *, acceptance_case_id=None, selected=None, fallback=None):
    return {
        "adoption_version": "adoption-v1",
        "comparison_id": comparison_id,
        "acceptance_case_id": acceptance_case_id,
        "decision": "ADOPTED" if selected else "REJECTED",
        "selected_run_id": selected,
        "fallback_run_id": fallback,
        "target": {
            "selection_version": "selection-v1",
            "canonical_product_ids": ["P1"],
            "center_ids": ["C1"],
            "trial_period_days": 30,
        },
        "decided_by": "owner@example.test",
        "reason": "正式比較と受入結果を確認",
    }


def _acceptance(acceptance, build_id: str, *, data_kind="REAL", approved=True):
    case = make_acceptance_case(
        {
            "acceptance_version": f"acceptance-{build_id}",
            "daily_build_id": build_id,
            "data_kind": data_kind,
            "expected_product_ids": ["P1", "P2", "P3"],
            "required_availability_mode": "ASSUMED",
            "min_usable_days_per_series": 30,
            "max_missing_rate": 0,
            "max_partial_invalid_rate": 0,
            "requested_by": "test@example.test",
            "purpose": "採用判断の受入fixture",
        }
    )
    acceptance.put_case(case)
    assert acceptance.claim().case_id == case.case_id
    outcome = "PASSED" if data_kind == "REAL" else "DRY_RUN"
    acceptance.complete(
        case.case_id,
        [],
        outcome,
        f"file:///reports/{case.case_id}.json",
        "a" * 64,
        f"file:///reports/{case.case_id}.md",
        "b" * 64,
    )
    if approved:
        acceptance.put_decision(
            make_acceptance_decision(
                case_id=case.case_id,
                decision_version="acceptance-decision-v1",
                decision="APPROVED",
                decided_by="owner@example.test",
                reason="技術判定と業務条件を確認",
            )
        )
    return case


def test_comparison_export_is_deterministic_safe_and_checksum_verified(tmp_path):
    api, runs, catalog, _, report_root, _, snapshot_id = _reporting_fixture(tmp_path)
    comparison_id, baseline_run, selected_run = _saved_comparison(
        api,
        runs,
        catalog,
        snapshot_id,
        purpose="=HYPERLINK(\"https://example.test\")",
    )
    request = {
        "export_version": "comparison-export-v1",
        "baseline_run_id": baseline_run,
        "requested_by": "=HYPERLINK(\"https://example.test\")",
    }

    first = api.post(f"/api/comparisons/{comparison_id}/exports", json=request)
    second = api.post(f"/api/comparisons/{comparison_id}/exports", json=request)

    assert first.status_code == second.status_code == 201
    assert first.json()["export_id"] == second.json()["export_id"]
    download = api.get(f"/api/exports/{first.json()['export_id']}")
    assert download.status_code == 200
    assert download.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(download.content.decode("utf-8-sig"))))
    assert len(rows) == 2
    assert all(row["requested_by"] == "local-admin" for row in rows)
    assert all(row["comparison_purpose"].startswith("'=") for row in rows)
    selected = next(row for row in rows if row["run_id"] == selected_run)
    assert float(selected["baseline_improvement_pct"]) == 100.0
    assert selected["own_planned_count"] == selected["run_planned_count"]
    assert (
        selected["official_truth_eligible_count"]
        == selected["official_common_success_count"]
    )
    assert rows[0]["metric_units"].endswith("mae/rmse/bias/under/over=quantity")
    assert api.get(
        f"/api/exports?comparison_id={comparison_id}"
    ).json()[0]["output_sha256"] == first.json()["output_sha256"]

    zero_baseline = api.post(
        f"/api/comparisons/{comparison_id}/exports",
        json={**request, "export_version": "zero-baseline-v1", "baseline_run_id": selected_run},
    )
    zero_rows = list(
        csv.DictReader(
            io.StringIO(
                api.get(f"/api/exports/{zero_baseline.json()['export_id']}")
                .content.decode("utf-8-sig")
            )
        )
    )
    assert all(row["baseline_improvement_pct"] == "" for row in zero_rows)

    path = snapshot_path(first.json()["output_uri"], report_root)
    path.write_bytes(b"tampered")
    assert api.get(f"/api/exports/{first.json()['export_id']}").status_code == 409


def test_export_rejects_unknown_baseline_client_path_and_unauthorized_access(tmp_path):
    api, runs, catalog, _, _, _, snapshot_id = _reporting_fixture(tmp_path)
    comparison_id, baseline_run, _ = _saved_comparison(api, runs, catalog, snapshot_id)
    request = {
        "export_version": "comparison-export-v1",
        "baseline_run_id": "missing",
        "requested_by": "test@example.test",
    }
    assert api.post(f"/api/comparisons/{comparison_id}/exports", json=request).status_code == 409
    with_path = {**request, "baseline_run_id": baseline_run, "output_uri": "file:///tmp/x"}
    assert api.post(f"/api/comparisons/{comparison_id}/exports", json=with_path).status_code == 422
    with TestClient(api.app) as unauthorized:
        assert unauthorized.get("/api/exports").status_code == 401


def test_rejected_adoption_is_immutable_and_queryable(tmp_path):
    api, runs, catalog, _, _, _, snapshot_id = _reporting_fixture(tmp_path)
    comparison_id, _, _ = _saved_comparison(api, runs, catalog, snapshot_id)
    request = _adoption_payload(comparison_id)

    first = api.post("/api/adoptions", json=request)
    second = api.post("/api/adoptions", json=request)

    assert first.status_code == second.status_code == 201
    assert first.json()["adoption_id"] == second.json()["adoption_id"]
    assert api.get(f"/api/adoptions/{first.json()['adoption_id']}").status_code == 200
    assert api.get(f"/api/adoptions?comparison_id={comparison_id}").json()[0][
        "decision"
    ] == "REJECTED"
    changed = {**request, "reason": "後から理由を変更"}
    assert api.post("/api/adoptions", json=changed).status_code == 409


def test_adoption_requires_real_approved_acceptance_and_official_fallback(tmp_path):
    api, runs, catalog, acceptance, _, _, original_snapshot_id = _reporting_fixture(tmp_path)
    original = catalog.get_snapshot(original_snapshot_id)
    snapshot = make_snapshot(
        {**original.manifest, "provenance": {"daily_build_id": "build-real-v1"}}
    )
    catalog.put_snapshot(snapshot)
    comparison_id, fallback_run, selected_run = _saved_comparison(
        api, runs, catalog, snapshot.snapshot_id
    )
    case = _acceptance(acceptance, "build-real-v1")
    request = _adoption_payload(
        comparison_id,
        acceptance_case_id=case.case_id,
        selected=selected_run,
        fallback=fallback_run,
    )

    response = api.post("/api/adoptions", json=request)

    assert response.status_code == 201, response.text
    assert response.json()["selected_run_id"] == selected_run
    context = api.get(f"/api/comparisons/{comparison_id}/adoption-context")
    assert context.status_code == 200
    assert context.json()["official_ranking_ready"] is True
    assert context.json()["canonical_product_ids"] == ["P1"]
    assert context.json()["center_ids"] == ["C1"]
    assert context.json()["acceptance_cases"] == [
        {
            "case_id": case.case_id,
            "acceptance_version": "acceptance-build-real-v1",
            "data_kind": "REAL",
            "status": "SUCCEEDED",
            "outcome": "PASSED",
            "latest_decision": "APPROVED",
            "eligible": True,
        }
    ]
    invalid = {**request, "adoption_version": "adoption-v2", "fallback_run_id": "missing"}
    assert api.post("/api/adoptions", json=invalid).status_code == 409


def test_anonymized_or_unapproved_acceptance_cannot_be_adopted(tmp_path):
    api, runs, catalog, acceptance, _, _, original_snapshot_id = _reporting_fixture(tmp_path)
    original = catalog.get_snapshot(original_snapshot_id)
    snapshot = make_snapshot(
        {**original.manifest, "provenance": {"daily_build_id": "build-dry-run"}}
    )
    catalog.put_snapshot(snapshot)
    comparison_id, fallback_run, selected_run = _saved_comparison(
        api, runs, catalog, snapshot.snapshot_id
    )
    case = _acceptance(
        acceptance, "build-dry-run", data_kind="ANONYMIZED", approved=False
    )
    request = _adoption_payload(
        comparison_id,
        acceptance_case_id=case.case_id,
        selected=selected_run,
        fallback=fallback_run,
    )

    response = api.post("/api/adoptions", json=request)

    assert response.status_code == 409
    assert "実データ" in response.json()["detail"]
