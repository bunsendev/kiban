"""Portable issues fixed, smoke-tested candidate packages before Pilot activation."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.api.candidate_packages import PortableCandidatePackages
from portable.api.change_applications import PortableChangeApplications
from portable.api.formal_pipeline import PortableFormalPipeline
from portable.api.production_handoff import ProductionHandoffError
from portable.api.runtime_assignments import PortableRuntimeAssignments
from portable.api.runtime_profiles import (
    RESOURCE_LIMITS,
    SUPPORTED_BASELINE_MODELS,
    enforce_resource_limits,
    supported_configuration,
)
from portable.runtime.paths import DataPaths
from tests.portable.test_p1_flow import approved_formal_pipeline, pilot_forecast_zip
from tests.test_phase3t_runtime_assignment_resolver import _approved_model_proposal


def _paths(tmp_path) -> DataPaths:
    paths = DataPaths(tmp_path)
    paths.ensure()
    return paths


def _issue(service, proposal_id: str, known_at: datetime) -> dict:
    return service.issue({
        "proposal_id": proposal_id,
        "actor": "package-issuer",
        "known_at": known_at.isoformat(),
        "confirm_shadow_package": True,
        "confirm_rollback_target": True,
    })


def _application(service, proposal: dict, receipt: dict, known_at: datetime) -> dict:
    value = service.create_application({
        "proposal_id": proposal["proposal_id"],
        "candidate_version": receipt["candidate_version"],
        "backup_reference": "backup-20261004-001",
        "backup_sha256": "a" * 64,
        "executor": "pilot-operator",
        "known_at": known_at.isoformat(),
        "confirm_pilot_only": True,
    })
    return service.evaluate_gate(value["application_id"], {
        "expected_revision": 0,
        "actor": "pilot-operator",
        "reason": "発行済み候補版とbackupを確認した",
        "confirm_audited_transition": True,
        "backup_verified": True,
        "candidate_staged": True,
        "candidate_manifest_sha256": receipt["manifest_sha256"],
        "smoke_checks": [
            {"name": "package_smoke", "passed": True, "evidence": "発行記録を照合"},
        ],
    })


@pytest.mark.parametrize("model_name", sorted(SUPPORTED_BASELINE_MODELS))
def test_package_runs_supported_model_and_is_selected_for_exact_scope(
    tmp_path, model_name: str,
) -> None:
    paths = _paths(tmp_path)
    database = paths.state / "shipment-actual-outcomes.sqlite3"
    proposal = _approved_model_proposal(
        database, version=f"{model_name}-candidate-v1", model_name=model_name
    )
    known_at = datetime.now(UTC)
    packages = PortableCandidatePackages(paths)

    receipt = _issue(packages, proposal["proposal_id"], known_at)
    repeated = _issue(packages, proposal["proposal_id"], known_at)

    assert repeated == receipt
    assert receipt["model_name"] == model_name
    assert receipt["smoke_test"]["status"] == "PASSED"
    assert receipt["smoke_test"]["forecast_count"] == 14
    assert receipt["resource_limits"] == RESOURCE_LIMITS
    application = _application(
        PortableChangeApplications(database), proposal, receipt, known_at
    )
    assert application["state"] == "PILOT_ACTIVE"

    selected = PortableRuntimeAssignments(paths).resolve_execution(
        "production-build-1", ["scope-v1"], "operator"
    )[0]
    assert selected["status"] == "CANDIDATE_SELECTED"
    assert selected["selected_configuration"]["model_name"] == model_name
    assert selected["candidate_manifest_sha256"] == receipt["manifest_sha256"]


def test_all_builtin_models_are_fixed_profiles_but_arbitrary_settings_are_rejected() -> None:
    base = {
        "version": "candidate-v1", "provider_id": "builtin-baseline",
        "preprocessing_version": "portable-daily-state-v1", "seed": 7,
        "resource_profile": "cpu-small", "params": {},
    }
    for model in SUPPORTED_BASELINE_MODELS:
        assert supported_configuration({**base, "model_name": model})
    assert not supported_configuration({**base, "model_name": "unknown-model"})
    assert not supported_configuration({
        **base, "model_name": "seasonal_naive_7", "params": {"x": 1},
    })
    with pytest.raises(ValueError, match="系列数"):
        enforce_resource_limits(
            {**base, "model_name": "seasonal_naive_7"},
            series=51, history_days=400, horizon_days=28,
        )


def test_unsupported_proposal_and_tampered_package_are_rejected(tmp_path) -> None:
    paths = _paths(tmp_path / "unsupported")
    database = paths.state / "shipment-actual-outcomes.sqlite3"
    unsupported = _approved_model_proposal(
        database, version="unknown-candidate-v1", model_name="unknown-model"
    )
    service = PortableCandidatePackages(paths)
    known_at = datetime.now(UTC)
    with pytest.raises(ProductionHandoffError, match="対応していない"):
        _issue(service, unsupported["proposal_id"], known_at)

    supported_paths = _paths(tmp_path / "supported")
    supported_database = supported_paths.state / "shipment-actual-outcomes.sqlite3"
    supported = _approved_model_proposal(
        supported_database,
        version="weekday-candidate-v1",
        model_name="same_weekday_mean_4",
    )
    supported_service = PortableCandidatePackages(supported_paths)
    receipt = _issue(supported_service, supported["proposal_id"], datetime.now(UTC))
    receipt_path = (
        supported_paths.state / "RuntimeCandidatePackages" / f"{receipt['package_id']}.json"
    )
    receipt_path.write_bytes(
        receipt_path.read_bytes().replace(b"same_weekday_mean_4", b"seasonal_naive_7")
    )
    with pytest.raises(ProductionHandoffError, match="整合性"):
        supported_service.overview()


def test_candidate_package_api_and_ui_asset_are_available(tmp_path) -> None:
    client = TestClient(create_app(tmp_path), base_url="http://localhost")
    response = client.get("/api/runtime-candidate-packages")
    assert response.status_code == 200
    assert response.json()["mode"] == "SHADOW"
    assert client.get("/candidate-packages.js").status_code == 200
    page = client.get("/").text
    assert 'id="candidate-package-form"' in page
    assert 'src="/candidate-packages.js"' in page


def test_packaged_challenger_completes_existing_production_worker(tmp_path) -> None:
    client = TestClient(create_app(tmp_path), base_url="http://localhost")
    approved = approved_formal_pipeline(client, pilot_forecast_zip())
    registration_id = approved["registration_id"]
    forecast = client.post(
        f"/api/formal-inventory/pipeline/{registration_id}/forecast",
        json={
            "actor": "forecast-reviewer", "reason": "identityと0 policyを確認",
            "confirm_identity_bridge": True, "confirm_zero_policy": True,
        },
    ).json()
    paths = DataPaths(tmp_path)
    database = paths.state / "shipment-actual-outcomes.sqlite3"
    pipeline = PortableFormalPipeline(paths)
    registration = pipeline.get_registration(registration_id)
    job = pipeline.inventory_store.get_job(registration["jobs"][0]["job_id"])
    assert job is not None and job.pilot_scope_version is not None
    proposal = _approved_model_proposal(
        database,
        version="production-moving-average-v1",
        model_name="moving_average_28",
        scope_version=job.pilot_scope_version,
    )
    known_at = datetime.now(UTC)
    receipt = _issue(PortableCandidatePackages(paths), proposal["proposal_id"], known_at)
    _application(PortableChangeApplications(database), proposal, receipt, known_at)

    queued = client.post(
        f"/api/formal-forecast/{forecast['build_id']}/production-run",
        json={
            "actor": "production-operator", "reason": "候補版Pilot予測を登録",
            "confirm_production_queue": True,
        },
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["model_name"] == "moving_average_28"
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        view = client.get(
            f"/api/formal-forecast/{forecast['build_id']}/production-run"
        ).json()
        if view["handoff"]["run_status"] == "SUCCEEDED":
            break
        time.sleep(0.05)
    assert view["handoff"]["run_status"] == "SUCCEEDED"
    assert view["handoff"]["model_name"] == "moving_average_28"
    assert len(view["handoff"]["point_predictions"]) == 140
