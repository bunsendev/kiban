"""Immutable domain objects for weekly reviews and learning candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from ..inventory_foundation.domain import canonical_datetime, canonical_decimal
from .contracts import LearningCandidateDecision, LearningCandidateType


@dataclass(frozen=True)
class FieldWeeklyReview:
    review_id: str
    week_start: date
    week_end: date
    pilot_scope_versions: tuple[str, ...]
    aggregation_version: str
    threshold_version: str
    report: dict
    reviewer: str
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


@dataclass(frozen=True)
class FieldLearningCandidate:
    candidate_id: str
    review_id: str
    candidate_type: LearningCandidateType
    evidence_count: int
    impact_quantity: Decimal | None
    reason_codes: tuple[str, ...]
    evidence_case_ids: tuple[str, ...]
    content_sha256: str


@dataclass(frozen=True)
class FieldLearningCandidateDecisionEvent:
    decision_event_id: str
    candidate_id: str
    revision: int
    decision: LearningCandidateDecision
    subject: str
    reason: str
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


def build_weekly_review(
    *,
    week_start: date,
    week_end: date,
    pilot_scope_versions: tuple[str, ...],
    aggregation_version: str,
    threshold_version: str,
    report: dict,
    reviewer: str,
    known_at: datetime,
    recorded_at: datetime,
) -> FieldWeeklyReview:
    if week_end < week_start or (week_end - week_start).days != 6:
        raise ValueError("週次集計期間は連続する7日間です")
    scopes = tuple(
        sorted({_required(value, "pilot_scope_version") for value in pilot_scope_versions})
    )
    if not scopes:
        raise ValueError("pilot_scope_versionは1件以上必要です")
    aggregation_version = _required(aggregation_version, "aggregation_version")
    threshold_version = _required(threshold_version, "threshold_version")
    reviewer = _required(reviewer, "reviewer")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    payload = {
        "format_version": "field-weekly-review-v1",
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "pilot_scope_versions": scopes,
        "aggregation_version": aggregation_version,
        "threshold_version": threshold_version,
        "report": report,
        "reviewer": reviewer,
        "known_at": canonical_datetime(known),
    }
    content_sha256 = _digest(payload)
    return FieldWeeklyReview(
        f"field-weekly-{content_sha256}", week_start, week_end, scopes,
        aggregation_version, threshold_version, report, reviewer, known, recorded,
        content_sha256,
    )


def build_learning_candidate(
    *,
    review_id: str,
    candidate_type: LearningCandidateType,
    evidence_count: int,
    impact_quantity: Decimal | int | str | None,
    reason_codes: tuple[str, ...],
    evidence_case_ids: tuple[str, ...],
) -> FieldLearningCandidate:
    review_id = _required(review_id, "review_id")
    if not isinstance(candidate_type, LearningCandidateType):
        raise ValueError("candidate_typeが不正です")
    if isinstance(evidence_count, bool) or evidence_count < 1:
        raise ValueError("evidence_countは1以上です")
    impact = _quantity(impact_quantity, "impact_quantity")
    reasons = tuple(sorted({_required(value, "reason_code") for value in reason_codes}))
    case_ids = tuple(sorted({_required(value, "evidence_case_id") for value in evidence_case_ids}))
    if len(case_ids) != evidence_count:
        raise ValueError("evidence_countとcase ID数が一致しません")
    payload = {
        "format_version": "field-learning-candidate-v1",
        "review_id": review_id,
        "candidate_type": candidate_type.value,
        "evidence_count": evidence_count,
        "impact_quantity": None if impact is None else canonical_decimal(impact),
        "reason_codes": reasons,
        "evidence_case_ids": case_ids,
    }
    content_sha256 = _digest(payload)
    return FieldLearningCandidate(
        f"field-candidate-{content_sha256}", review_id, candidate_type,
        evidence_count, impact, reasons, case_ids, content_sha256,
    )


def build_learning_candidate_decision_event(
    *,
    candidate_id: str,
    expected_revision: int,
    decision: LearningCandidateDecision,
    subject: str,
    reason: str,
    known_at: datetime,
    recorded_at: datetime,
) -> FieldLearningCandidateDecisionEvent:
    candidate_id = _required(candidate_id, "candidate_id")
    if isinstance(expected_revision, bool) or expected_revision < 0:
        raise ValueError("expected_revisionは0以上です")
    if not isinstance(decision, LearningCandidateDecision):
        raise ValueError("decisionが不正です")
    subject = _required(subject, "subject")
    reason = _required(reason, "reason")
    if len(reason) > 500:
        raise ValueError("reasonは500文字以下です")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    revision = expected_revision + 1
    payload = {
        "format_version": "field-learning-candidate-decision-v1",
        "candidate_id": candidate_id,
        "revision": revision,
        "decision": decision.value,
        "subject": subject,
        "reason": reason,
        "known_at": canonical_datetime(known),
    }
    content_sha256 = _digest(payload)
    return FieldLearningCandidateDecisionEvent(
        f"field-candidate-decision-{content_sha256}", candidate_id, revision,
        decision, subject, reason, known, recorded, content_sha256,
    )


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label}は必須です")
    return normalized


def _quantity(value, label: str) -> Decimal | None:
    if value is None:
        return None
    normalized = Decimal(canonical_decimal(value))
    if normalized < 0:
        raise ValueError(f"{label}は0以上です")
    return normalized


def _known_and_recorded(known_at: datetime, recorded_at: datetime):
    canonical_datetime(known_at, "known_at")
    canonical_datetime(recorded_at, "recorded_at")
    known = known_at.astimezone(UTC)
    recorded = recorded_at.astimezone(UTC)
    if known > recorded:
        raise ValueError("known_atはrecorded_at以前です")
    return known, recorded


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
