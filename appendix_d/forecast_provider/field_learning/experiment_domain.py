"""Immutable investigation plans, comparison runs, and human decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from ..inventory_foundation.domain import canonical_datetime
from .contracts import LearningExperimentDecision, LearningExperimentTarget
from .weekly_domain import _known_and_recorded, _required


@dataclass(frozen=True)
class FieldLearningExperimentPlan:
    plan_id: str
    candidate_id: str
    target: LearningExperimentTarget
    baseline_version: str
    challenger_version: str
    hypothesis: str
    evidence_case_ids: tuple[str, ...]
    subject: str
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


@dataclass(frozen=True)
class FieldLearningExperimentRun:
    run_id: str
    plan_id: str
    result_version: str
    source_sha256: str
    report: dict
    subject: str
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


@dataclass(frozen=True)
class FieldLearningExperimentDecisionEvent:
    decision_event_id: str
    run_id: str
    revision: int
    decision: LearningExperimentDecision
    subject: str
    reason: str
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


def build_experiment_plan(
    *, candidate_id: str, target: LearningExperimentTarget,
    baseline_version: str, challenger_version: str, hypothesis: str,
    evidence_case_ids: tuple[str, ...], subject: str,
    known_at: datetime, recorded_at: datetime,
) -> FieldLearningExperimentPlan:
    candidate_id = _required(candidate_id, "candidate_id")
    if not isinstance(target, LearningExperimentTarget):
        raise ValueError("targetが不正です")
    baseline_version = _required(baseline_version, "baseline_version")
    challenger_version = _required(challenger_version, "challenger_version")
    if baseline_version == challenger_version:
        raise ValueError("Baseline版とChallenger版は別の値にしてください")
    hypothesis = _required(hypothesis, "hypothesis")
    if len(hypothesis) > 500:
        raise ValueError("hypothesisは500文字以下です")
    cases = tuple(sorted({_required(value, "evidence_case_id") for value in evidence_case_ids}))
    if not cases:
        raise ValueError("比較対象caseは1件以上必要です")
    subject = _required(subject, "subject")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    payload = {
        "format_version": "field-learning-experiment-plan-v1",
        "candidate_id": candidate_id,
        "target": target.value,
        "baseline_version": baseline_version,
        "challenger_version": challenger_version,
        "hypothesis": hypothesis,
        "evidence_case_ids": cases,
        "subject": subject,
        "known_at": canonical_datetime(known),
    }
    digest = _digest(payload)
    return FieldLearningExperimentPlan(
        f"field-experiment-plan-{digest}", candidate_id, target,
        baseline_version, challenger_version, hypothesis, cases, subject,
        known, recorded, digest,
    )


def build_experiment_run(
    *, plan_id: str, result_version: str, source_sha256: str,
    report: dict, subject: str, known_at: datetime, recorded_at: datetime,
) -> FieldLearningExperimentRun:
    plan_id = _required(plan_id, "plan_id")
    result_version = _required(result_version, "result_version")
    source_sha256 = _required(source_sha256, "source_sha256").lower()
    if len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256):
        raise ValueError("source_sha256が不正です")
    subject = _required(subject, "subject")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    payload = {
        "format_version": "field-learning-experiment-run-v1",
        "plan_id": plan_id,
        "result_version": result_version,
        "source_sha256": source_sha256,
        "report": report,
        "subject": subject,
        "known_at": canonical_datetime(known),
    }
    digest = _digest(payload)
    return FieldLearningExperimentRun(
        f"field-experiment-run-{digest}", plan_id, result_version,
        source_sha256, report, subject, known, recorded, digest,
    )


def build_experiment_decision_event(
    *, run_id: str, expected_revision: int, decision: LearningExperimentDecision,
    subject: str, reason: str, known_at: datetime, recorded_at: datetime,
) -> FieldLearningExperimentDecisionEvent:
    run_id = _required(run_id, "run_id")
    if isinstance(expected_revision, bool) or expected_revision < 0:
        raise ValueError("expected_revisionは0以上です")
    if not isinstance(decision, LearningExperimentDecision):
        raise ValueError("decisionが不正です")
    subject = _required(subject, "subject")
    reason = _required(reason, "reason")
    if len(reason) > 500:
        raise ValueError("reasonは500文字以下です")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    revision = expected_revision + 1
    payload = {
        "format_version": "field-learning-experiment-decision-v1",
        "run_id": run_id,
        "revision": revision,
        "decision": decision.value,
        "subject": subject,
        "reason": reason,
        "known_at": canonical_datetime(known),
    }
    digest = _digest(payload)
    return FieldLearningExperimentDecisionEvent(
        f"field-experiment-decision-{digest}", run_id, revision, decision,
        subject, reason, known, recorded, digest,
    )


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
