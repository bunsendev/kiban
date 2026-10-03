"""Portable adapter for immutable weekly learning reviews and human decisions."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from forecast_provider.field_learning import (
    FieldLearningConflict,
    LearningCandidateDecision,
    SqliteFieldLearningStore,
    build_learning_candidate,
    build_learning_candidate_decision_event,
    build_weekly_review,
)
from forecast_provider.field_learning.weekly import build_weekly_review_bundle
from forecast_provider.inventory_foundation.domain import canonical_decimal

from .production_handoff import ProductionHandoffError


class LearningReviewConflict(ProductionHandoffError):
    """Raised when an outdated candidate revision is submitted."""


class PortableWeeklyLearningReviews:
    def __init__(self, database: Path) -> None:
        self.store = SqliteFieldLearningStore(database)

    def overview(self) -> dict:
        reviews = [self._summary(value) for value in self.store.list_weekly_reviews()]
        return {
            "mode": "SHADOW",
            "available_pilot_scope_versions": self.store.list_pilot_scope_versions(),
            "reviews": reviews,
            "notice": "週次集計と改善候補は参考情報です。設定へ自動反映しません。",
        }

    def create(self, payload: dict) -> dict:
        week_end = _date(payload.get("week_end"), "週の終了日")
        scopes = payload.get("pilot_scope_versions")
        if not isinstance(scopes, list) or not all(isinstance(value, str) for value in scopes):
            raise ProductionHandoffError("Pilot Scope版を1件以上選択してください")
        known_at = _datetime(payload.get("known_at"), "集計基準日時")
        reviewer = _text(payload.get("reviewer"), "確認者", 100)
        aggregation = _text(payload.get("aggregation_version"), "集計版", 100)
        threshold = _text(payload.get("threshold_version"), "判定基準版", 100)
        minimum = payload.get("minimum_evidence_count")
        if isinstance(minimum, bool) or not isinstance(minimum, int):
            raise ProductionHandoffError("候補化する最小根拠件数は整数です")
        if payload.get("confirm_shadow_review") is not True:
            raise ProductionHandoffError("SHADOW週次確認であることを選択してください")
        try:
            review, candidates = build_weekly_review_bundle(
                self.store,
                week_end=week_end,
                pilot_scope_versions=tuple(scopes),
                aggregation_version=aggregation,
                threshold_version=threshold,
                minimum_evidence_count=minimum,
                reviewer=reviewer,
                known_at=known_at,
                recorded_at=datetime.now(UTC),
            )
            self.store.put_weekly_review(review, candidates)
        except ValueError as exc:
            raise ProductionHandoffError(str(exc)) from exc
        return self.view(review.review_id)

    def view(self, review_id: str) -> dict:
        review = self.store.get_weekly_review(review_id)
        if review is None:
            raise ProductionHandoffError("週次集計版が見つかりません")
        _verify_review(review)
        candidates = []
        for item in self.store.list_learning_candidates(review.review_id):
            _verify_candidate(item)
            events = self.store.list_learning_candidate_decisions(item.candidate_id)
            for event in events:
                _verify_candidate_decision(event)
            latest = events[-1] if events else None
            candidates.append({
                "candidate_id": item.candidate_id,
                "candidate_type": item.candidate_type.value,
                "evidence_count": item.evidence_count,
                "impact_quantity_cases": (
                    None if item.impact_quantity is None
                    else canonical_decimal(item.impact_quantity)
                ),
                "reason_codes": list(item.reason_codes),
                "evidence_case_ids": list(item.evidence_case_ids),
                "status": "PENDING" if latest is None else latest.decision.value,
                "revision": 0 if latest is None else latest.revision,
                "decision_history": [
                    {
                        "decision_event_id": event.decision_event_id,
                        "revision": event.revision,
                        "decision": event.decision.value,
                        "subject": event.subject,
                        "reason": event.reason,
                        "known_at": event.known_at.isoformat(),
                        "recorded_at": event.recorded_at.isoformat(),
                    }
                    for event in events
                ],
            })
        return {
            "review_id": review.review_id,
            "week_start": review.week_start.isoformat(),
            "week_end": review.week_end.isoformat(),
            "pilot_scope_versions": list(review.pilot_scope_versions),
            "aggregation_version": review.aggregation_version,
            "threshold_version": review.threshold_version,
            "reviewer": review.reviewer,
            "known_at": review.known_at.isoformat(),
            "recorded_at": review.recorded_at.isoformat(),
            "content_sha256": review.content_sha256,
            "report": review.report,
            "candidates": candidates,
        }

    def decide(self, candidate_id: str, payload: dict) -> dict:
        candidate = self.store.get_learning_candidate(candidate_id)
        if candidate is None:
            raise ProductionHandoffError("改善候補が見つかりません")
        expected = payload.get("expected_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ProductionHandoffError("expected_revisionは0以上の整数です")
        try:
            decision = LearningCandidateDecision(str(payload.get("decision") or ""))
        except ValueError as exc:
            raise ProductionHandoffError("承認または却下を選択してください") from exc
        subject = _text(payload.get("subject"), "確認者", 100)
        reason = _text(payload.get("reason"), "判断理由", 500)
        if payload.get("confirm_no_automatic_application") is not True:
            raise ProductionHandoffError("自動反映しない判断であることを確認してください")
        now = datetime.now(UTC)
        try:
            event = build_learning_candidate_decision_event(
                candidate_id=candidate.candidate_id,
                expected_revision=expected,
                decision=decision,
                subject=subject,
                reason=reason,
                known_at=now,
                recorded_at=now,
            )
            self.store.append_learning_candidate_decision(event, expected)
        except FieldLearningConflict as exc:
            events = self.store.list_learning_candidate_decisions(candidate_id)
            latest = events[-1] if events else None
            if not (
                latest is not None
                and latest.revision == expected + 1
                and latest.decision is decision
                and latest.subject == subject
                and latest.reason == reason
            ):
                raise LearningReviewConflict(str(exc)) from exc
        return self.view(candidate.review_id)

    @staticmethod
    def _summary(review) -> dict:
        current = review.report["current"]
        return {
            "review_id": review.review_id,
            "week_start": review.week_start.isoformat(),
            "week_end": review.week_end.isoformat(),
            "pilot_scope_versions": list(review.pilot_scope_versions),
            "aggregation_version": review.aggregation_version,
            "reviewer": review.reviewer,
            "reference_case_count": current["reference_case_count"],
            "actual_count": current["comparison_coverage"]["actual_any"],
        }


def _verify_review(value) -> None:
    rebuilt = build_weekly_review(
        week_start=value.week_start,
        week_end=value.week_end,
        pilot_scope_versions=value.pilot_scope_versions,
        aggregation_version=value.aggregation_version,
        threshold_version=value.threshold_version,
        report=value.report,
        reviewer=value.reviewer,
        known_at=value.known_at,
        recorded_at=value.recorded_at,
    )
    if rebuilt.review_id != value.review_id or rebuilt.content_sha256 != value.content_sha256:
        raise ProductionHandoffError("週次集計版の整合性を確認できません")


def _verify_candidate(value) -> None:
    rebuilt = build_learning_candidate(
        review_id=value.review_id,
        candidate_type=value.candidate_type,
        evidence_count=value.evidence_count,
        impact_quantity=value.impact_quantity,
        reason_codes=value.reason_codes,
        evidence_case_ids=value.evidence_case_ids,
    )
    if (
        rebuilt.candidate_id != value.candidate_id
        or rebuilt.content_sha256 != value.content_sha256
    ):
        raise ProductionHandoffError("改善候補の整合性を確認できません")


def _verify_candidate_decision(value) -> None:
    rebuilt = build_learning_candidate_decision_event(
        candidate_id=value.candidate_id,
        expected_revision=value.revision - 1,
        decision=value.decision,
        subject=value.subject,
        reason=value.reason,
        known_at=value.known_at,
        recorded_at=value.recorded_at,
    )
    if (
        rebuilt.decision_event_id != value.decision_event_id
        or rebuilt.content_sha256 != value.content_sha256
    ):
        raise ProductionHandoffError("改善候補の判断履歴の整合性を確認できません")


def _text(value, label: str, maximum: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise ProductionHandoffError(f"{label}は1〜{maximum}文字です")
    return result


def _date(value, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ProductionHandoffError(f"{label}はYYYY-MM-DDです") from exc


def _datetime(value, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductionHandoffError(f"{label}はtimezone付きISO日時です") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ProductionHandoffError(f"{label}はtimezone付きISO日時です")
    return result
