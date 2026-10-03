"""Persistence mixin for immutable weekly reviews and candidate decisions."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from ..inventory_foundation.domain import canonical_decimal
from .contracts import LearningCandidateDecision, LearningCandidateType
from .domain import FieldLearningConflict
from .weekly_domain import (
    FieldLearningCandidate,
    FieldLearningCandidateDecisionEvent,
    FieldWeeklyReview,
)


class WeeklyLearningStoreMixin:
    def put_weekly_review(
        self,
        review: FieldWeeklyReview,
        candidates: tuple[FieldLearningCandidate, ...],
    ) -> FieldWeeklyReview:
        if any(item.review_id != review.review_id for item in candidates):
            raise ValueError("改善候補と週次集計版が一致しません")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO field_weekly_reviews VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(review_id) DO NOTHING",
                (
                    review.review_id, review.week_start.isoformat(), review.week_end.isoformat(),
                    _json(review.pilot_scope_versions), review.aggregation_version,
                    review.threshold_version, _json(review.report), review.reviewer,
                    review.known_at.isoformat(), review.recorded_at.isoformat(),
                    review.content_sha256,
                ),
            )
            for item in sorted(candidates, key=lambda value: value.candidate_id):
                db.execute(
                    "INSERT INTO field_learning_candidates VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(candidate_id) DO NOTHING",
                    (
                        item.candidate_id, item.review_id, item.candidate_type.value,
                        item.evidence_count,
                        None if item.impact_quantity is None
                        else canonical_decimal(item.impact_quantity),
                        _json(item.reason_codes), _json(item.evidence_case_ids),
                        item.content_sha256,
                    ),
                )
        current = self.get_weekly_review(review.review_id)
        if current is None or current.content_sha256 != review.content_sha256:
            raise ValueError("同じ週次集計版の内容は変更できません")
        return current

    def get_weekly_review(self, review_id: str) -> FieldWeeklyReview | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM field_weekly_reviews WHERE review_id=?", (review_id,)
            ).fetchone()
        return None if row is None else _weekly_review(row)

    def list_weekly_reviews(self, *, limit: int = 50) -> list[FieldWeeklyReview]:
        if not 1 <= limit <= 200:
            raise ValueError("limitは1以上200以下です")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_weekly_reviews "
                "ORDER BY week_end DESC,recorded_at DESC,review_id LIMIT ?", (limit,)
            ).fetchall()
        return [_weekly_review(row) for row in rows]

    def list_learning_candidates(self, review_id: str) -> list[FieldLearningCandidate]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_learning_candidates WHERE review_id=? "
                "ORDER BY candidate_type,candidate_id", (review_id,)
            ).fetchall()
        return [_learning_candidate(row) for row in rows]

    def get_learning_candidate(self, candidate_id: str) -> FieldLearningCandidate | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM field_learning_candidates WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
        return None if row is None else _learning_candidate(row)

    def append_learning_candidate_decision(
        self,
        event: FieldLearningCandidateDecisionEvent,
        expected_revision: int,
    ) -> FieldLearningCandidateDecisionEvent:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                f"SELECT candidate_id FROM field_learning_candidates "
                f"WHERE candidate_id=?{self.lock_clause}", (event.candidate_id,),
            ).fetchone() is None:
                raise KeyError(event.candidate_id)
            current = self._latest_revision(
                db, "field_learning_candidate_decision_events", event.candidate_id,
                id_column="candidate_id",
            )
            if current != expected_revision or event.revision != expected_revision + 1:
                raise FieldLearningConflict("ほかの利用者が先に改善候補を判断しました")
            db.execute(
                "INSERT INTO field_learning_candidate_decision_events "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    event.decision_event_id, event.candidate_id, event.revision,
                    event.decision.value, event.subject, event.reason,
                    event.known_at.isoformat(), event.recorded_at.isoformat(),
                    event.content_sha256,
                ),
            )
        return event

    def list_learning_candidate_decisions(
        self, candidate_id: str
    ) -> list[FieldLearningCandidateDecisionEvent]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_learning_candidate_decision_events "
                "WHERE candidate_id=? ORDER BY revision", (candidate_id,)
            ).fetchall()
        return [_candidate_decision(row) for row in rows]

    def list_pilot_scope_versions(self) -> list[str]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT DISTINCT pilot_scope_version FROM field_reference_cases "
                "ORDER BY pilot_scope_version"
            ).fetchall()
        return [row["pilot_scope_version"] for row in rows]


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _weekly_review(row) -> FieldWeeklyReview:
    return FieldWeeklyReview(
        row["review_id"], date.fromisoformat(str(row["week_start"])),
        date.fromisoformat(str(row["week_end"])),
        tuple(json.loads(row["pilot_scope_versions_json"])), row["aggregation_version"],
        row["threshold_version"], json.loads(row["report_json"]), row["reviewer"],
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])), row["content_sha256"],
    )


def _learning_candidate(row) -> FieldLearningCandidate:
    return FieldLearningCandidate(
        row["candidate_id"], row["review_id"],
        LearningCandidateType(row["candidate_type"]), int(row["evidence_count"]),
        None if row["impact_quantity"] is None else Decimal(row["impact_quantity"]),
        tuple(json.loads(row["reason_codes_json"])),
        tuple(json.loads(row["evidence_case_ids_json"])), row["content_sha256"],
    )


def _candidate_decision(row) -> FieldLearningCandidateDecisionEvent:
    return FieldLearningCandidateDecisionEvent(
        row["decision_event_id"], row["candidate_id"], int(row["revision"]),
        LearningCandidateDecision(row["decision"]), row["subject"], row["reason"],
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])), row["content_sha256"],
    )
