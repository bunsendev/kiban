"""Immutable evidence for resolving a Pilot runtime assignment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..inventory_foundation.domain import canonical_datetime
from .contracts import RuntimeAssignmentStatus
from .formal_change_domain import _configuration, _digest
from .weekly_domain import _known_and_recorded, _required


@dataclass(frozen=True)
class FieldRuntimeAssignmentResolution:
    resolution_id: str
    execution_key: str
    pilot_scope_version: str
    status: RuntimeAssignmentStatus
    selected_version: str
    selected_configuration: dict
    application_id: str | None
    application_revision: int | None
    proposal_id: str | None
    candidate_manifest_sha256: str | None
    reason_code: str
    actor: str
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


def build_runtime_assignment_resolution(
    *, execution_key: str, pilot_scope_version: str,
    status: RuntimeAssignmentStatus, selected_version: str,
    selected_configuration: dict, application_id: str | None,
    application_revision: int | None, proposal_id: str | None,
    candidate_manifest_sha256: str | None, reason_code: str, actor: str,
    known_at: datetime, recorded_at: datetime,
) -> FieldRuntimeAssignmentResolution:
    execution_key = _required(execution_key, "execution_key")
    pilot_scope_version = _required(pilot_scope_version, "pilot_scope_version")
    if not isinstance(status, RuntimeAssignmentStatus):
        raise ValueError("statusが不正です")
    selected_version = _required(selected_version, "selected_version")
    configuration = _configuration(selected_configuration, "selected_configuration")
    application_id = _optional(application_id)
    proposal_id = _optional(proposal_id)
    if (application_id is None) != (application_revision is None):
        raise ValueError("application_idとrevisionは同時に指定します")
    if application_revision is not None and (
        isinstance(application_revision, bool) or application_revision < 1
    ):
        raise ValueError("application_revisionは1以上です")
    candidate_manifest_sha256 = _optional(candidate_manifest_sha256)
    if candidate_manifest_sha256 is not None and (
        len(candidate_manifest_sha256) != 64
        or any(value not in "0123456789abcdef" for value in candidate_manifest_sha256)
    ):
        raise ValueError("candidate_manifest_sha256は64桁のSHA-256です")
    reason_code = _required(reason_code, "reason_code")
    actor = _required(actor, "actor")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    payload = {
        "format_version": "field-runtime-assignment-resolution-v1",
        "execution_key": execution_key,
        "pilot_scope_version": pilot_scope_version,
        "status": status.value,
        "selected_version": selected_version,
        "selected_configuration": configuration,
        "application_id": application_id,
        "application_revision": application_revision,
        "proposal_id": proposal_id,
        "candidate_manifest_sha256": candidate_manifest_sha256,
        "reason_code": reason_code,
        "actor": actor,
        "known_at": canonical_datetime(known),
    }
    digest = _digest(payload)
    return FieldRuntimeAssignmentResolution(
        f"field-runtime-resolution-{digest}", execution_key, pilot_scope_version,
        status, selected_version, configuration, application_id,
        application_revision, proposal_id, candidate_manifest_sha256,
        reason_code, actor, known, recorded, digest,
    )


def _optional(value: object) -> str | None:
    if value is None:
        return None
    return _required(str(value), "optional_value")
