"""Portable resolves audited Pilot assignments without silently changing scope."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.api.change_applications import PortableChangeApplications
from portable.api.formal_changes import PortableFormalChanges
from portable.api.runtime_assignments import (
    BASELINE_CONFIGURATION,
    PortableRuntimeAssignments,
    RuntimeAssignmentError,
)
from portable.runtime.paths import DataPaths
from tests.test_phase3t_formal_change_proposals import _recommended_run


def _candidate_configuration(version: str) -> dict:
    return {**BASELINE_CONFIGURATION, "version": version}


def _approved_model_proposal(
    database, version: str = "candidate-model-v1", run_id: str | None = None,
) -> dict:
    if run_id is None:
        _, run = _recommended_run(database)
        run_id = run["run_id"]
    service = PortableFormalChanges(database)
    proposal = service.create_proposal({
        "run_id": run_id,
        "change_target": "FORECAST_MODEL",
        "current_configuration": BASELINE_CONFIGURATION,
        "proposed_configuration": _candidate_configuration(version),
        "application_scope": {"pilot_scope_versions": ["scope-v1"]},
        "acceptance_criteria": ["Baseline以上の精度を維持する"],
        "rollback_conditions": ["精度悪化または証跡不整合を検出する"],
        "rollback_target_version": BASELINE_CONFIGURATION["version"],
        "author": "proposal-author",
        "known_at": datetime.now(UTC).isoformat(),
        "confirm_no_automatic_application": True,
    })
    return service.decide(proposal["proposal_id"], {
        "expected_revision": 0,
        "decision": "APPROVED_FOR_IMPLEMENTATION",
        "approver": "independent-approver",
        "reason": "固定Scope向け候補版を承認する",
        "confirm_separate_approval": True,
    })


def _manifest(paths, proposal: dict, candidate_version: str) -> str:
    root = paths.state / "RuntimeCandidates"
    root.mkdir(parents=True, exist_ok=True)
    raw = json.dumps({
        "format": "bunsen-portable-runtime-candidate-v1",
        "candidate_version": candidate_version,
        "proposal_id": proposal["proposal_id"],
        "runtime_configuration": proposal["proposed_configuration"],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    (root / f"{candidate_version}.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _activate(
    paths, version: str = "candidate-model-v1", run_id: str | None = None,
) -> tuple[dict, str]:
    database = paths.state / "shipment-actual-outcomes.sqlite3"
    proposal = _approved_model_proposal(database, version, run_id)
    manifest_sha = _manifest(paths, proposal, version)
    service = PortableChangeApplications(database)
    application = service.create_application({
        "proposal_id": proposal["proposal_id"],
        "candidate_version": version,
        "backup_reference": "backup-20261004-001",
        "backup_sha256": "a" * 64,
        "executor": "pilot-operator",
        "known_at": datetime.now(UTC).isoformat(),
        "confirm_pilot_only": True,
    })
    application = service.evaluate_gate(application["application_id"], {
        "expected_revision": 0,
        "actor": "pilot-operator",
        "reason": "候補manifestと起動試験を確認した",
        "confirm_audited_transition": True,
        "backup_verified": True,
        "candidate_staged": True,
        "candidate_manifest_sha256": manifest_sha,
        "smoke_checks": [
            {"name": "API起動", "passed": True, "evidence": "ready応答"},
            {"name": "Scope確認", "passed": True, "evidence": "scope-v1のみ"},
        ],
    })
    return application, manifest_sha


def _paths(tmp_path) -> DataPaths:
    paths = DataPaths(tmp_path)
    paths.ensure()
    return paths


def test_candidate_is_selected_only_for_exact_active_scope(tmp_path) -> None:
    paths = _paths(tmp_path)
    application, manifest_sha = _activate(paths)
    service = PortableRuntimeAssignments(paths)

    selected = service.resolve_execution("build-1", ["scope-v1"], "operator")[0]
    assert selected["status"] == "CANDIDATE_SELECTED"
    assert selected["selected_version"] == "candidate-model-v1"
    assert selected["application_id"] == application["application_id"]
    assert selected["candidate_manifest_sha256"] == manifest_sha

    baseline = service.resolve_execution("build-2", ["scope-v2"], "operator")[0]
    assert baseline["status"] == "BASELINE_SELECTED"
    assert baseline["selected_configuration"] == BASELINE_CONFIGURATION
    assert baseline["application_id"] is None


def test_manifest_hash_mismatch_and_multiple_assignments_block_execution(tmp_path) -> None:
    paths = _paths(tmp_path)
    first, _ = _activate(paths)
    candidate = paths.state / "RuntimeCandidates" / "candidate-model-v1.json"
    candidate.write_bytes(candidate.read_bytes() + b"\n")
    service = PortableRuntimeAssignments(paths)
    blocked = service.resolve_execution("build-hash", ["scope-v1"], "operator")[0]
    assert blocked["status"] == "BLOCKED"
    assert blocked["reason_code"] == "CANDIDATE_MANIFEST_HASH_MISMATCH"

    candidate.unlink()
    run_id = PortableFormalChanges(service.database).view_proposal(
        first["proposal_id"]
    )["run_id"]
    _activate(paths, "candidate-model-v2", run_id)
    conflict = service.resolve_execution("build-conflict", ["scope-v1"], "operator")[0]
    assert conflict["status"] == "BLOCKED"
    assert conflict["reason_code"] == "MULTIPLE_ACTIVE_ASSIGNMENTS"


def test_mixed_candidate_and_baseline_scopes_do_not_share_one_run(tmp_path) -> None:
    paths = _paths(tmp_path)
    _activate(paths)
    service = PortableRuntimeAssignments(paths)
    result = service.resolve_execution(
        "build-mixed", ["scope-v1", "scope-v2"], "operator"
    )
    assert {item["status"] for item in result} == {"BLOCKED"}
    assert {item["reason_code"] for item in result} == {
        "MIXED_RUNTIME_CONFIGURATION_UNSUPPORTED"
    }


def test_missing_candidate_blocks_but_revoked_approval_returns_to_baseline(tmp_path) -> None:
    paths = _paths(tmp_path)
    application, _ = _activate(paths)
    candidate = paths.state / "RuntimeCandidates" / "candidate-model-v1.json"
    candidate.unlink()
    service = PortableRuntimeAssignments(paths)
    missing = service.resolve_execution("build-missing", ["scope-v1"], "operator")[0]
    assert missing["status"] == "BLOCKED"
    assert missing["reason_code"] == "CANDIDATE_MANIFEST_NOT_UNIQUE"

    PortableFormalChanges(service.database).decide(application["proposal_id"], {
        "expected_revision": 1,
        "decision": "REJECTED",
        "approver": "independent-approver",
        "reason": "新しい根拠により候補版の承認を取り消す",
        "confirm_separate_approval": True,
    })
    revoked = service.resolve_execution("build-revoked", ["scope-v1"], "operator")[0]
    assert revoked["status"] == "BASELINE_SELECTED"
    assert revoked["reason_code"] == "NO_ACTIVE_ASSIGNMENT"


def test_runtime_resolution_is_append_only_and_tamper_evident(tmp_path) -> None:
    paths = _paths(tmp_path)
    service = PortableRuntimeAssignments(paths)
    resolution = service.resolve_execution("build-1", ["scope-v1"], "operator")[0]
    assert service.overview()["resolutions"][0] == resolution

    with sqlite3.connect(service.database) as db:
        db.execute(
            "UPDATE field_runtime_assignment_resolutions SET selected_version=? "
            "WHERE resolution_id=?",
            ("tampered", resolution["resolution_id"]),
        )
    with pytest.raises(RuntimeAssignmentError, match="整合性"):
        service.overview()


def test_runtime_assignment_api_and_step_16_assets_are_available(tmp_path) -> None:
    client = TestClient(create_app(tmp_path), base_url="http://localhost")
    response = client.get("/api/runtime-assignments")
    assert response.status_code == 200
    assert response.json()["mode"] == "SHADOW"
    assert client.get("/runtime-assignments.js").status_code == 200
    assert 'id="runtime-assignments"' in client.get("/").text
