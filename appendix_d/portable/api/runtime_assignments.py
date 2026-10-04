"""Resolve audited Pilot assignments to executable Portable configurations."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from forecast_provider.field_learning import (
    RuntimeAssignmentStatus,
    SqliteFieldLearningStore,
    build_runtime_assignment_resolution,
)

from .formal_shipment_daily import canonical_json, sha256

BASELINE_CONFIGURATION = {
    "version": "builtin-baseline-v1",
    "provider_id": "builtin-baseline",
    "model_name": "seasonal_naive_7",
    "preprocessing_version": "portable-daily-state-v1",
    "seed": 7,
    "resource_profile": "cpu-small",
    "params": {},
}
MANIFEST_FORMAT = "bunsen-portable-runtime-candidate-v1"


class RuntimeAssignmentError(ValueError):
    pass


class PortableRuntimeAssignments:
    def __init__(self, paths) -> None:
        from .change_applications import PortableChangeApplications

        self.database = paths.state / "shipment-actual-outcomes.sqlite3"
        self.store = SqliteFieldLearningStore(self.database)
        self.applications = PortableChangeApplications(self.database)
        self.candidate_root = paths.state / "RuntimeCandidates"
        self.candidate_root.mkdir(parents=True, exist_ok=True)

    def overview(self) -> dict:
        return {
            "mode": "SHADOW",
            "baseline_configuration": BASELINE_CONFIGURATION,
            "installed_candidates": self._installed_candidate_views(),
            "resolutions": [
                _resolution_view(item)
                for item in self.store.list_runtime_assignment_resolutions(limit=200)
            ],
            "notice": (
                "固定Pilot Scopeと配置manifestが一致する場合だけ候補版を選びます。"
                "対象外ScopeはBaselineを維持し、競合や不一致では実行を止めます。"
            ),
        }

    def resolve_execution(
        self, execution_key: str, pilot_scope_versions: list[str], actor: str,
        *, known_at: datetime | None = None,
    ) -> list[dict]:
        execution_key = _text(execution_key, "実行キー", 300)
        actor = _text(actor, "実行担当者", 100)
        scopes = sorted({_text(item, "Pilot Scope版", 200) for item in pilot_scope_versions})
        if not scopes:
            raise RuntimeAssignmentError("実行対象のPilot Scopeがありません")
        known = (known_at or datetime.now(UTC)).astimezone(UTC)
        specs = [self._resolve_one(scope) for scope in scopes]
        executable = [item for item in specs if item["status"] != "BLOCKED"]
        signatures = {
            sha256(canonical_json(item["selected_configuration"])) for item in executable
        }
        if len(signatures) > 1:
            for item in specs:
                item.update({
                    "status": "BLOCKED",
                    "reason_code": "MIXED_RUNTIME_CONFIGURATION_UNSUPPORTED",
                })
        result = []
        for spec in specs:
            try:
                value = build_runtime_assignment_resolution(
                    execution_key=execution_key,
                    pilot_scope_version=spec["pilot_scope_version"],
                    status=RuntimeAssignmentStatus(spec["status"]),
                    selected_version=spec["selected_version"],
                    selected_configuration=spec["selected_configuration"],
                    application_id=spec.get("application_id"),
                    application_revision=spec.get("application_revision"),
                    proposal_id=spec.get("proposal_id"),
                    candidate_manifest_sha256=spec.get("candidate_manifest_sha256"),
                    reason_code=spec["reason_code"], actor=actor,
                    known_at=known, recorded_at=datetime.now(UTC),
                )
                self.store.put_runtime_assignment_resolution(value)
            except ValueError as exc:
                raise RuntimeAssignmentError(str(exc)) from exc
            result.append(_resolution_view(value))
        return result

    def _resolve_one(self, scope: str) -> dict:
        active = []
        integrity_failed = False
        for item in self.store.list_change_applications(limit=500):
            try:
                value = self.applications.view_application(item.application_id)
            except ValueError:
                integrity_failed = True
                continue
            if (
                value["state"] in {"PILOT_ACTIVE", "ACCEPTED"}
                and value["source_approval_is_current"]
                and scope in _scope_versions(value["application_scope"])
            ):
                active.append(value)
        if integrity_failed:
            return _blocked_spec(scope, "APPLICATION_INTEGRITY_UNVERIFIED")
        if not active:
            return _baseline_spec(scope)
        if len(active) > 1:
            return _blocked_spec(scope, "MULTIPLE_ACTIVE_ASSIGNMENTS")
        application = active[0]
        common = {
            "pilot_scope_version": scope,
            "application_id": application["application_id"],
            "application_revision": application["revision"],
            "proposal_id": application["proposal"]["proposal_id"],
            "selected_version": application["candidate_version"],
            "selected_configuration": application["proposal"]["proposed_configuration"],
        }
        if application["proposal"]["change_target"] != "FORECAST_MODEL":
            return {**common, "status": "BLOCKED", "reason_code": "UNSUPPORTED_CHANGE_TARGET"}
        gate_sha = _gate_manifest_sha(application)
        if gate_sha is None:
            return {**common, "status": "BLOCKED", "reason_code": "GATE_MANIFEST_HASH_MISSING"}
        manifests = self._candidate_manifests(application["candidate_version"])
        if len(manifests) != 1:
            return {
                **common, "status": "BLOCKED",
                "candidate_manifest_sha256": gate_sha,
                "reason_code": "CANDIDATE_MANIFEST_NOT_UNIQUE",
            }
        manifest, manifest_sha = manifests[0]
        common["candidate_manifest_sha256"] = manifest_sha
        if manifest_sha != gate_sha:
            return {
                **common, "status": "BLOCKED",
                "reason_code": "CANDIDATE_MANIFEST_HASH_MISMATCH",
            }
        if (
            manifest.get("format") != MANIFEST_FORMAT
            or manifest.get("candidate_version") != application["candidate_version"]
            or manifest.get("proposal_id") != application["proposal"]["proposal_id"]
            or manifest.get("runtime_configuration")
            != application["proposal"]["proposed_configuration"]
        ):
            return {
                **common, "status": "BLOCKED",
                "reason_code": "CANDIDATE_MANIFEST_CONTRACT_MISMATCH",
            }
        if not _supported_configuration(common["selected_configuration"]):
            return {**common, "status": "BLOCKED", "reason_code": "RUNTIME_ADAPTER_UNSUPPORTED"}
        return {
            **common, "status": "CANDIDATE_SELECTED",
            "reason_code": "ACTIVE_ASSIGNMENT_MATCHED",
        }

    def _candidate_manifests(self, candidate_version: str) -> list[tuple[dict, str]]:
        result = []
        for path in sorted(self.candidate_root.glob("*.json")):
            try:
                raw = path.read_bytes()
                value = json.loads(raw)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(value, dict) and value.get("candidate_version") == candidate_version:
                result.append((value, hashlib.sha256(raw).hexdigest()))
        return result

    def _installed_candidate_views(self) -> list[dict]:
        result = []
        for path in sorted(self.candidate_root.glob("*.json")):
            try:
                raw = path.read_bytes()
                value = json.loads(raw)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            result.append({
                "candidate_version": value.get("candidate_version"),
                "proposal_id": value.get("proposal_id"),
                "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                "supported": _supported_configuration(value.get("runtime_configuration")),
            })
        return result


def _scope_versions(value: dict) -> set[str]:
    raw = value.get("pilot_scope_versions") if isinstance(value, dict) else None
    if not isinstance(raw, list):
        return set()
    return {str(item).strip() for item in raw if str(item).strip()}


def _gate_manifest_sha(application: dict) -> str | None:
    for event in reversed(application["events"]):
        if (
            event["transition"] == "PILOT_GATE_EVALUATED"
            and event["resulting_state"] == "PILOT_ACTIVE"
        ):
            value = event["evidence"].get("candidate_manifest_sha256")
            return value if isinstance(value, str) else None
    return None


def _supported_configuration(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    required = {
        "version", "provider_id", "model_name", "preprocessing_version",
        "seed", "resource_profile", "params",
    }
    return (
        set(value) == required
        and isinstance(value.get("version"), str) and bool(value["version"].strip())
        and value.get("provider_id") == "builtin-baseline"
        and value.get("model_name") == "seasonal_naive_7"
        and value.get("preprocessing_version") == "portable-daily-state-v1"
        and value.get("seed") == 7
        and value.get("resource_profile") == "cpu-small"
        and value.get("params") == {}
    )


def _baseline_spec(scope: str) -> dict:
    return {
        "pilot_scope_version": scope,
        "status": "BASELINE_SELECTED",
        "selected_version": BASELINE_CONFIGURATION["version"],
        "selected_configuration": BASELINE_CONFIGURATION,
        "reason_code": "NO_ACTIVE_ASSIGNMENT",
    }


def _blocked_spec(scope: str, reason: str) -> dict:
    return {
        **_baseline_spec(scope), "status": "BLOCKED", "reason_code": reason,
    }


def _resolution_view(value) -> dict:
    rebuilt = build_runtime_assignment_resolution(
        execution_key=value.execution_key,
        pilot_scope_version=value.pilot_scope_version, status=value.status,
        selected_version=value.selected_version,
        selected_configuration=value.selected_configuration,
        application_id=value.application_id,
        application_revision=value.application_revision,
        proposal_id=value.proposal_id,
        candidate_manifest_sha256=value.candidate_manifest_sha256,
        reason_code=value.reason_code, actor=value.actor,
        known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if (
        rebuilt.resolution_id != value.resolution_id
        or rebuilt.content_sha256 != value.content_sha256
    ):
        raise RuntimeAssignmentError("実行時版選択証跡の整合性を確認できません")
    return {
        "resolution_id": value.resolution_id,
        "execution_key": value.execution_key,
        "pilot_scope_version": value.pilot_scope_version,
        "status": value.status.value,
        "selected_version": value.selected_version,
        "selected_configuration": value.selected_configuration,
        "selected_configuration_sha256": sha256(canonical_json(value.selected_configuration)),
        "application_id": value.application_id,
        "application_revision": value.application_revision,
        "proposal_id": value.proposal_id,
        "candidate_manifest_sha256": value.candidate_manifest_sha256,
        "reason_code": value.reason_code,
        "actor": value.actor,
        "known_at": value.known_at.isoformat(),
        "recorded_at": value.recorded_at.isoformat(),
        "content_sha256": value.content_sha256,
    }


def _text(value, label: str, maximum: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise RuntimeAssignmentError(f"{label}は1〜{maximum}文字です")
    return result
