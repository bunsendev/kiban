"""Immutable Pilot application plans and append-only transition evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime

from ..inventory_foundation.domain import canonical_datetime
from .contracts import ChangeApplicationState, ChangeApplicationTransition
from .formal_change_domain import _configuration, _digest
from .weekly_domain import _known_and_recorded, _required


@dataclass(frozen=True)
class FieldChangeApplication:
    application_id: str
    proposal_id: str
    source_proposal_decision_revision: int
    candidate_version: str
    application_scope: dict
    backup_reference: str
    backup_sha256: str
    executor: str
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


@dataclass(frozen=True)
class FieldChangeApplicationEvent:
    event_id: str
    application_id: str
    revision: int
    transition: ChangeApplicationTransition
    resulting_state: ChangeApplicationState
    actor: str
    reason: str
    evidence: dict
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


def build_change_application(
    *, proposal_id: str, source_proposal_decision_revision: int,
    candidate_version: str, application_scope: dict,
    backup_reference: str, backup_sha256: str, executor: str,
    known_at: datetime, recorded_at: datetime,
) -> FieldChangeApplication:
    proposal_id = _required(proposal_id, "proposal_id")
    if (
        isinstance(source_proposal_decision_revision, bool)
        or source_proposal_decision_revision < 1
    ):
        raise ValueError("source_proposal_decision_revisionは1以上です")
    candidate_version = _required(candidate_version, "candidate_version")
    if len(candidate_version) > 100:
        raise ValueError("candidate_versionは100文字以下です")
    scope = _configuration(application_scope, "application_scope")
    backup_reference = _required(backup_reference, "backup_reference")
    if len(backup_reference) > 300:
        raise ValueError("backup_referenceは300文字以下です")
    backup_sha256 = str(backup_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", backup_sha256):
        raise ValueError("backup_sha256は64桁のSHA-256です")
    executor = _required(executor, "executor")
    if len(executor) > 100:
        raise ValueError("executorは100文字以下です")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    payload = {
        "format_version": "field-change-application-v1",
        "proposal_id": proposal_id,
        "source_proposal_decision_revision": source_proposal_decision_revision,
        "candidate_version": candidate_version,
        "application_scope": scope,
        "backup_reference": backup_reference,
        "backup_sha256": backup_sha256,
        "executor": executor,
        "known_at": canonical_datetime(known),
    }
    digest = _digest(payload)
    return FieldChangeApplication(
        f"field-change-application-{digest}", proposal_id,
        source_proposal_decision_revision, candidate_version, scope,
        backup_reference, backup_sha256, executor, known, recorded, digest,
    )


def build_change_application_event(
    *, application_id: str, expected_revision: int,
    transition: ChangeApplicationTransition, resulting_state: ChangeApplicationState,
    actor: str, reason: str, evidence: dict,
    known_at: datetime, recorded_at: datetime,
) -> FieldChangeApplicationEvent:
    application_id = _required(application_id, "application_id")
    if isinstance(expected_revision, bool) or expected_revision < 0:
        raise ValueError("expected_revisionは0以上です")
    if not isinstance(transition, ChangeApplicationTransition):
        raise ValueError("transitionが不正です")
    if not isinstance(resulting_state, ChangeApplicationState):
        raise ValueError("resulting_stateが不正です")
    actor = _required(actor, "actor")
    if len(actor) > 100:
        raise ValueError("actorは100文字以下です")
    reason = _required(reason, "reason")
    if len(reason) > 500:
        raise ValueError("reasonは500文字以下です")
    normalized_evidence = _configuration(evidence, "evidence")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    revision = expected_revision + 1
    payload = {
        "format_version": "field-change-application-event-v1",
        "application_id": application_id,
        "revision": revision,
        "transition": transition.value,
        "resulting_state": resulting_state.value,
        "actor": actor,
        "reason": reason,
        "evidence": normalized_evidence,
        "known_at": canonical_datetime(known),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return FieldChangeApplicationEvent(
        f"field-change-application-event-{digest}", application_id, revision,
        transition, resulting_state, actor, reason, normalized_evidence,
        known, recorded, digest,
    )
