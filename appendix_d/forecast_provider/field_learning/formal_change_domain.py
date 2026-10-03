"""Immutable formal change proposals and independent approval decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from ..inventory_foundation.domain import canonical_datetime
from .contracts import FormalChangeDecision, FormalChangeTarget
from .weekly_domain import _known_and_recorded, _required


@dataclass(frozen=True)
class FieldFormalChangeProposal:
    proposal_id: str
    run_id: str
    source_decision_revision: int
    change_target: FormalChangeTarget
    current_configuration: dict
    proposed_configuration: dict
    application_scope: dict
    acceptance_criteria: tuple[str, ...]
    rollback_conditions: tuple[str, ...]
    rollback_target_version: str
    author: str
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


@dataclass(frozen=True)
class FieldFormalChangeDecisionEvent:
    decision_event_id: str
    proposal_id: str
    revision: int
    decision: FormalChangeDecision
    approver: str
    reason: str
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


def build_formal_change_proposal(
    *, run_id: str, source_decision_revision: int,
    change_target: FormalChangeTarget, current_configuration: dict,
    proposed_configuration: dict, application_scope: dict,
    acceptance_criteria: tuple[str, ...], rollback_conditions: tuple[str, ...],
    rollback_target_version: str, author: str,
    known_at: datetime, recorded_at: datetime,
) -> FieldFormalChangeProposal:
    run_id = _required(run_id, "run_id")
    if isinstance(source_decision_revision, bool) or source_decision_revision < 1:
        raise ValueError("source_decision_revisionは1以上です")
    if not isinstance(change_target, FormalChangeTarget):
        raise ValueError("change_targetが不正です")
    current = _configuration(current_configuration, "current_configuration")
    proposed = _configuration(proposed_configuration, "proposed_configuration")
    if current == proposed:
        raise ValueError("現行設定と変更後設定には差分が必要です")
    scope = _configuration(application_scope, "application_scope")
    criteria = _statements(acceptance_criteria, "acceptance_criteria")
    rollback = _statements(rollback_conditions, "rollback_conditions")
    rollback_target_version = _required(rollback_target_version, "rollback_target_version")
    author = _required(author, "author")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    payload = {
        "format_version": "field-formal-change-proposal-v1",
        "run_id": run_id,
        "source_decision_revision": source_decision_revision,
        "change_target": change_target.value,
        "current_configuration": current,
        "proposed_configuration": proposed,
        "application_scope": scope,
        "acceptance_criteria": criteria,
        "rollback_conditions": rollback,
        "rollback_target_version": rollback_target_version,
        "author": author,
        "known_at": canonical_datetime(known),
    }
    digest = _digest(payload)
    return FieldFormalChangeProposal(
        f"field-formal-change-{digest}", run_id, source_decision_revision,
        change_target, current, proposed, scope, criteria, rollback,
        rollback_target_version, author, known, recorded, digest,
    )


def build_formal_change_decision_event(
    *, proposal_id: str, expected_revision: int, decision: FormalChangeDecision,
    approver: str, reason: str, known_at: datetime, recorded_at: datetime,
) -> FieldFormalChangeDecisionEvent:
    proposal_id = _required(proposal_id, "proposal_id")
    if isinstance(expected_revision, bool) or expected_revision < 0:
        raise ValueError("expected_revisionは0以上です")
    if not isinstance(decision, FormalChangeDecision):
        raise ValueError("decisionが不正です")
    approver = _required(approver, "approver")
    reason = _required(reason, "reason")
    if len(reason) > 500:
        raise ValueError("reasonは500文字以下です")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    revision = expected_revision + 1
    payload = {
        "format_version": "field-formal-change-decision-v1",
        "proposal_id": proposal_id,
        "revision": revision,
        "decision": decision.value,
        "approver": approver,
        "reason": reason,
        "known_at": canonical_datetime(known),
    }
    digest = _digest(payload)
    return FieldFormalChangeDecisionEvent(
        f"field-formal-change-decision-{digest}", proposal_id, revision,
        decision, approver, reason, known, recorded, digest,
    )


def _configuration(value: dict, label: str) -> dict:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{label}は空でないJSON objectです")
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        normalized = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}はJSONとして保存可能な値です") from exc
    if len(encoded.encode("utf-8")) > 32 * 1024:
        raise ValueError(f"{label}は32KB以下です")
    return normalized


def _statements(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{label}は一覧です")
    result = tuple(_required(value, label) for value in values)
    if not result or len(result) > 20 or any(len(value) > 500 for value in result):
        raise ValueError(f"{label}は1〜20件、各500文字以下です")
    return result


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
