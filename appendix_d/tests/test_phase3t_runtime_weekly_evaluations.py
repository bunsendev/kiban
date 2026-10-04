"""Runtime-aware weekly reviews compare only identical observed outcomes."""

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from forecast_provider.field_learning import (
    FieldMode,
    OperatorDecision,
    OperatorReasonCode,
    SqliteFieldLearningStore,
    build_actual_outcome_event,
    build_operator_decision_event,
    build_reference_case,
)
from portable.api.app import create_app
from portable.api.formal_shipment_daily import canonical_json, sha256
from portable.api.learning_reviews import PortableWeeklyLearningReviews
from portable.api.production_handoff import PortableProductionHandoff
from portable.api.runtime_assignments import PortableRuntimeAssignments
from portable.runtime.paths import DataPaths
from tests.test_phase3t_runtime_assignment_resolver import _activate


def _jan(index: int) -> str:
    body = f"49012345{index:04d}"
    weighted = sum(
        int(digit) * (3 if offset % 2 == 0 else 1)
        for offset, digit in enumerate(reversed(body))
    )
    return body + str((10 - weighted % 10) % 10)


def _case(store, *, run_id: str, scope: str, forecast: str, jan: str):
    now = datetime.now(UTC)
    value = build_reference_case(
        business_date=date(2026, 9, 25), jan=jan,
        canonical_product_id="product-runtime-review",
        warehouse_id="warehouse-east", forecast_center_id="center-east",
        forecast_run_id=run_id, inventory_snapshot_id="snapshot-runtime-review",
        pilot_scope_version=scope, identity_bridge_version="bridge-v1",
        system_forecast_quantity=forecast, system_reference_quantity="5",
        policy_version="policy-v1", mode=FieldMode.SHADOW,
        known_at=now, recorded_at=now,
    )
    store.put_reference_case(value)
    return value


def _actual(store, case, source_sha: str = "9" * 64) -> None:
    now = datetime.now(UTC)
    value = build_actual_outcome_event(
        case_id=case.case_id, expected_revision=0, source_version="actual-v1",
        source_sha256=source_sha, actual_shipped_quantity="11",
        actual_demand_quantity="12", stockout_quantity="1",
        expired_quantity=None, interwarehouse_transfer_quantity="0",
        known_at=now, recorded_at=now,
    )
    store.append_actual_outcome(value, 0)


def _receipt(paths, build_id: str, run_id: str, resolution: dict) -> None:
    configuration = resolution["selected_configuration"]
    value = {
        "format": "portable-production-handoff-v1",
        "build_id": build_id,
        "run_id": run_id,
        "provider_id": configuration["provider_id"],
        "model_name": configuration["model_name"],
        "runtime_version": resolution["selected_version"],
        "runtime_configuration_sha256": resolution[
            "selected_configuration_sha256"
        ],
        "runtime_resolutions": [resolution],
    }
    value["receipt_sha256"] = sha256(canonical_json(value))
    root = PortableProductionHandoff(paths).receipt_root
    (root / f"{build_id}.json").write_bytes(canonical_json(value))


def test_runtime_review_compares_same_actual_and_keeps_unattributed_case(tmp_path) -> None:
    paths = DataPaths(tmp_path)
    paths.ensure()
    _activate(paths)
    assignments = PortableRuntimeAssignments(paths)
    baseline = assignments.resolve_execution(
        "build-baseline", ["scope-v2"], "operator"
    )[0]
    candidate = assignments.resolve_execution(
        "build-candidate", ["scope-v1"], "operator"
    )[0]
    assert baseline["status"] == "BASELINE_SELECTED"
    assert candidate["status"] == "CANDIDATE_SELECTED"
    _receipt(paths, "build-baseline", "forecast-baseline", baseline)
    _receipt(paths, "build-candidate", "forecast-candidate", candidate)

    store = SqliteFieldLearningStore(paths.state / "shipment-actual-outcomes.sqlite3")
    jan = _jan(900)
    baseline_case = _case(
        store, run_id="forecast-baseline", scope="scope-v2", forecast="15", jan=jan
    )
    candidate_case = _case(
        store, run_id="forecast-candidate", scope="scope-v1", forecast="13", jan=jan
    )
    legacy_case = _case(
        store, run_id="forecast-legacy", scope="scope-v2", forecast="14", jan=_jan(901)
    )
    _actual(store, baseline_case)
    _actual(store, candidate_case)
    decision = build_operator_decision_event(
        case=candidate_case, expected_revision=0,
        operator_decision=OperatorDecision.INCREASED, operator_quantity="6",
        operator_reason_code=OperatorReasonCode.EXPECTED_LARGE_ORDER,
        operator_comment=None, subject="operator", known_at=datetime.now(UTC),
        recorded_at=datetime.now(UTC),
    )
    store.append_operator_decision(decision, 0)

    weekly = PortableWeeklyLearningReviews(
        paths.state / "shipment-actual-outcomes.sqlite3"
    ).create({
        "week_end": "2026-09-27",
        "pilot_scope_versions": ["scope-v1", "scope-v2"],
        "aggregation_version": "weekly-v1",
        "threshold_version": "threshold-v1",
        "minimum_evidence_count": 1,
        "reviewer": "reviewer",
        "known_at": datetime.now(UTC).isoformat(),
        "confirm_shadow_review": True,
    })
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    payload = {
        "weekly_review_id": weekly["review_id"],
        "evaluation_version": "runtime-weekly-v1",
        "reviewer": "reviewer",
        "confirm_same_actual_shadow": True,
    }
    created = client.post("/api/runtime-weekly-evaluations", json=payload)
    assert created.status_code == 201
    value = created.json()
    assert client.post("/api/runtime-weekly-evaluations", json=payload).json() == value
    report = value["report"]
    assert report["source_reference_case_count"] == 3
    assert report["attributed_case_count"] == 2
    assert report["unattributed_case_count"] == 1
    assert report["blockers"] == [{
        "code": "RUNTIME_EVIDENCE_NOT_FOUND", "count": 1,
        "case_ids": [legacy_case.case_id],
    }]
    comparison = report["pairwise_comparisons"][0]
    assert comparison["status"] == "READY"
    assert comparison["same_actual_count"] == 1
    assert comparison["baseline_forecast_kpis"]["mae_cases"] == "3"
    assert comparison["candidate_forecast_kpis"]["mae_cases"] == "1"
    assert comparison["candidate_minus_baseline"]["mae_cases"] == "-2"
    assert comparison["shared_actual_business_kpis"] == {
        "stockout_cases": "1",
        "expired_cases": None,
        "interwarehouse_transfer_cases": "0",
    }
    candidate_group = next(
        item for item in report["runtime_groups"]
        if item["assignment_status"] == "CANDIDATE_SELECTED"
    )
    assert candidate_group["operator_kpis"]["change_count"] == 1
    assert candidate_group["operational_coverage"]["expired_cases"] == 0

    restarted = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    loaded = restarted.get(
        f"/api/runtime-weekly-evaluations/{value['evaluation_id']}"
    )
    assert loaded.status_code == 200
    assert loaded.json() == value
    page = restarted.get("/").text
    assert "12-2. 実際に使った予測モデル版ごとに結果を比較" in page
    assert restarted.get("/runtime-weekly-evaluations.js").status_code == 200


def test_runtime_review_rejects_mismatched_actual_provenance_and_tampering(
    tmp_path,
) -> None:
    paths = DataPaths(tmp_path)
    paths.ensure()
    _activate(paths)
    assignments = PortableRuntimeAssignments(paths)
    first = assignments.resolve_execution("build-a", ["scope-v2"], "operator")[0]
    second = assignments.resolve_execution("build-b", ["scope-v1"], "operator")[0]
    _receipt(paths, "build-a", "run-a", first)
    _receipt(paths, "build-b", "run-b", second)
    store = SqliteFieldLearningStore(paths.state / "shipment-actual-outcomes.sqlite3")
    jan = _jan(902)
    left = _case(store, run_id="run-a", scope="scope-v2", forecast="11", jan=jan)
    right = _case(store, run_id="run-b", scope="scope-v1", forecast="10", jan=jan)
    _actual(store, left, "1" * 64)
    _actual(store, right, "2" * 64)
    weekly = PortableWeeklyLearningReviews(
        paths.state / "shipment-actual-outcomes.sqlite3"
    ).create({
        "week_end": "2026-09-27",
        "pilot_scope_versions": ["scope-v1", "scope-v2"],
        "aggregation_version": "weekly-v1", "threshold_version": "threshold-v1",
        "minimum_evidence_count": 1, "reviewer": "reviewer",
        "known_at": datetime.now(UTC).isoformat(), "confirm_shadow_review": True,
    })
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    response = client.post("/api/runtime-weekly-evaluations", json={
        "weekly_review_id": weekly["review_id"],
        "evaluation_version": "runtime-weekly-v1", "reviewer": "reviewer",
        "confirm_same_actual_shadow": True,
    })
    assert response.status_code == 201
    value = response.json()
    comparison = value["report"]["pairwise_comparisons"][0]
    assert comparison["status"] == "BLOCKED_ACTUAL_MISMATCH"
    assert comparison["same_actual_count"] == 0

    target = paths.state / "RuntimeWeeklyEvaluations" / f"{value['evaluation_id']}.json"
    target.write_bytes(target.read_bytes().replace(b"runtime-weekly-v1", b"tampered-weekly-v1"))
    loaded = client.get(f"/api/runtime-weekly-evaluations/{value['evaluation_id']}")
    assert loaded.status_code == 404
    assert "整合性" in loaded.json()["detail"]
