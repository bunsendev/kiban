"""Portable adapter for approved-candidate SHADOW comparison experiments."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from forecast_provider.field_learning import (
    FieldLearningConflict,
    LearningCandidateDecision,
    LearningExperimentDecision,
    LearningExperimentTarget,
    SqliteFieldLearningStore,
    build_experiment_decision_event,
    build_experiment_plan,
    build_experiment_run,
    build_learning_candidate,
    build_learning_candidate_decision_event,
)
from forecast_provider.field_learning.experiment import build_experiment_report
from forecast_provider.inventory_foundation.domain import canonical_decimal

from .learning_reviews import LearningReviewConflict
from .production_handoff import ProductionHandoffError

CSV_COLUMNS = ("case_id", "challenger_quantity")


class PortableLearningExperiments:
    def __init__(self, database: Path) -> None:
        self.store = SqliteFieldLearningStore(database)

    def overview(self) -> dict:
        approved = []
        for review in self.store.list_weekly_reviews(limit=200):
            for candidate in self.store.list_learning_candidates(review.review_id):
                decisions = self.store.list_learning_candidate_decisions(candidate.candidate_id)
                if decisions and decisions[-1].decision is LearningCandidateDecision.APPROVED:
                    approved.append({
                        "candidate_id": candidate.candidate_id,
                        "candidate_type": candidate.candidate_type.value,
                        "review_id": review.review_id,
                        "week_start": review.week_start.isoformat(),
                        "week_end": review.week_end.isoformat(),
                        "evidence_count": candidate.evidence_count,
                        "decision_revision": decisions[-1].revision,
                    })
        return {
            "mode": "SHADOW",
            "approved_candidates": approved,
            "plans": [self._plan_summary(value) for value in self.store.list_experiment_plans()],
            "notice": "比較結果は正式設定へ自動反映されません。",
        }

    def create_plan(self, payload: dict) -> dict:
        candidate_id = _text(payload.get("candidate_id"), "改善候補", 200)
        candidate = self.store.get_learning_candidate(candidate_id)
        if candidate is None:
            raise ProductionHandoffError("改善候補が見つかりません")
        candidate_decisions = self.store.list_learning_candidate_decisions(candidate_id)
        _verify_candidate(candidate)
        for value in candidate_decisions:
            _verify_candidate_decision(value)
        if (
            not candidate_decisions
            or candidate_decisions[-1].decision is not LearningCandidateDecision.APPROVED
        ):
            raise ProductionHandoffError("APPROVEDの改善候補だけを調査できます")
        try:
            target = LearningExperimentTarget(str(payload.get("target") or ""))
        except ValueError as exc:
            raise ProductionHandoffError("比較対象を選択してください") from exc
        known_at = _datetime(payload.get("known_at"), "計画基準日時")
        if known_at < candidate_decisions[-1].known_at:
            raise ProductionHandoffError("計画基準日時は候補承認日時以降です")
        if payload.get("confirm_shadow_experiment") is not True:
            raise ProductionHandoffError("SHADOW比較であることを確認してください")
        try:
            plan = build_experiment_plan(
                candidate_id=candidate_id,
                target=target,
                baseline_version=_text(payload.get("baseline_version"), "Baseline版", 100),
                challenger_version=_text(payload.get("challenger_version"), "Challenger版", 100),
                hypothesis=_text(payload.get("hypothesis"), "検証仮説", 500),
                evidence_case_ids=candidate.evidence_case_ids,
                subject=_text(payload.get("subject"), "作成者", 100),
                known_at=known_at,
                recorded_at=datetime.now(UTC),
            )
            self.store.put_experiment_plan(plan)
        except ValueError as exc:
            raise ProductionHandoffError(str(exc)) from exc
        return self.view_plan(plan.plan_id)

    def view_plan(self, plan_id: str) -> dict:
        plan = self.store.get_experiment_plan(plan_id)
        if plan is None:
            raise ProductionHandoffError("調査計画が見つかりません")
        _verify_plan(plan)
        return {
            **self._plan_summary(plan),
            "hypothesis": plan.hypothesis,
            "evidence_case_ids": list(plan.evidence_case_ids),
            "subject": plan.subject,
            "known_at": plan.known_at.isoformat(),
            "recorded_at": plan.recorded_at.isoformat(),
            "content_sha256": plan.content_sha256,
            "runs": [self._run_view(value) for value in self.store.list_experiment_runs(plan_id)],
        }

    def template(self, plan_id: str) -> bytes:
        plan = self.store.get_experiment_plan(plan_id)
        if plan is None:
            raise ProductionHandoffError("調査計画が見つかりません")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
        writer.writeheader()
        for case_id in plan.evidence_case_ids:
            writer.writerow({"case_id": case_id, "challenger_quantity": ""})
        return output.getvalue().encode("utf-8-sig")

    def create_run(self, plan_id: str, payload: dict) -> dict:
        plan = self.store.get_experiment_plan(plan_id)
        if plan is None:
            raise ProductionHandoffError("調査計画が見つかりません")
        if payload.get("confirm_same_case_set") is not True:
            raise ProductionHandoffError("同一case集合で比較することを確認してください")
        raw = _base64(payload.get("csv_base64"))
        values = _parse_challenger_csv(raw)
        known_at = _datetime(payload.get("known_at"), "比較基準日時")
        if known_at < plan.known_at:
            raise ProductionHandoffError("比較基準日時は計画基準日時以降です")
        try:
            report = build_experiment_report(self.store, plan, values, known_at=known_at)
            run = build_experiment_run(
                plan_id=plan.plan_id,
                result_version=_text(payload.get("result_version"), "結果版", 100),
                source_sha256=hashlib.sha256(raw).hexdigest(),
                report=report,
                subject=_text(payload.get("subject"), "実行者", 100),
                known_at=known_at,
                recorded_at=datetime.now(UTC),
            )
            self.store.put_experiment_run(run)
        except ValueError as exc:
            raise ProductionHandoffError(str(exc)) from exc
        return self.view_plan(plan.plan_id)

    def decide(self, run_id: str, payload: dict) -> dict:
        run = self.store.get_experiment_run(run_id)
        if run is None:
            raise ProductionHandoffError("比較runが見つかりません")
        expected = payload.get("expected_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ProductionHandoffError("expected_revisionは0以上の整数です")
        try:
            decision = LearningExperimentDecision(str(payload.get("decision") or ""))
        except ValueError as exc:
            raise ProductionHandoffError("採用候補または見送りを選択してください") from exc
        if (
            decision is LearningExperimentDecision.RECOMMEND_FORMAL_CHANGE
            and run.report["coverage"]["comparable_count"] < 1
        ):
            raise ProductionHandoffError("共通比較対象がないため正式変更案を推奨できません")
        if payload.get("confirm_no_automatic_application") is not True:
            raise ProductionHandoffError("正式設定へ自動反映しないことを確認してください")
        now = datetime.now(UTC)
        subject = _text(payload.get("subject"), "確認者", 100)
        reason = _text(payload.get("reason"), "判断理由", 500)
        try:
            event = build_experiment_decision_event(
                run_id=run_id, expected_revision=expected, decision=decision,
                subject=subject, reason=reason, known_at=now, recorded_at=now,
            )
            self.store.append_experiment_decision(event, expected)
        except FieldLearningConflict as exc:
            events = self.store.list_experiment_decisions(run_id)
            latest = events[-1] if events else None
            if not (
                latest and latest.revision == expected + 1 and latest.decision is decision
                and latest.subject == subject and latest.reason == reason
            ):
                raise LearningReviewConflict(str(exc)) from exc
        return self.view_plan(run.plan_id)

    def _run_view(self, run) -> dict:
        _verify_run(run)
        decisions = self.store.list_experiment_decisions(run.run_id)
        for value in decisions:
            _verify_decision(value)
        latest = decisions[-1] if decisions else None
        return {
            "run_id": run.run_id,
            "result_version": run.result_version,
            "source_sha256": run.source_sha256,
            "report": run.report,
            "subject": run.subject,
            "known_at": run.known_at.isoformat(),
            "recorded_at": run.recorded_at.isoformat(),
            "content_sha256": run.content_sha256,
            "status": "PENDING" if latest is None else latest.decision.value,
            "revision": 0 if latest is None else latest.revision,
            "decision_history": [
                {
                    "decision_event_id": value.decision_event_id,
                    "revision": value.revision,
                    "decision": value.decision.value,
                    "subject": value.subject,
                    "reason": value.reason,
                    "known_at": value.known_at.isoformat(),
                    "recorded_at": value.recorded_at.isoformat(),
                }
                for value in decisions
            ],
        }

    @staticmethod
    def _plan_summary(plan) -> dict:
        return {
            "plan_id": plan.plan_id,
            "candidate_id": plan.candidate_id,
            "target": plan.target.value,
            "baseline_version": plan.baseline_version,
            "challenger_version": plan.challenger_version,
            "case_count": len(plan.evidence_case_ids),
        }


def _parse_challenger_csv(raw: bytes) -> dict[str, Decimal]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProductionHandoffError("比較CSVはUTF-8で保存してください") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
        raise ProductionHandoffError("比較CSVの列をテンプレートに合わせてください")
    values: dict[str, Decimal] = {}
    seen: set[str] = set()
    for row in reader:
        case_id = str(row.get("case_id") or "").strip()
        raw_quantity = str(row.get("challenger_quantity") or "").strip()
        if not case_id or case_id in seen:
            raise ProductionHandoffError("case_idは必須かつ一意です")
        seen.add(case_id)
        if not raw_quantity:
            continue
        try:
            quantity = Decimal(canonical_decimal(raw_quantity))
        except (ValueError, InvalidOperation) as exc:
            raise ProductionHandoffError("Challenger数量は0以上の数値です") from exc
        if quantity < 0:
            raise ProductionHandoffError("Challenger数量は0以上の数値です")
        values[case_id] = quantity
    return values


def _base64(value) -> bytes:
    try:
        raw = base64.b64decode(str(value or ""), validate=True)
    except ValueError as exc:
        raise ProductionHandoffError("比較CSVを読み込めません") from exc
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ProductionHandoffError("比較CSVは1byte以上2MB以下です")
    return raw


def _verify_plan(value) -> None:
    rebuilt = build_experiment_plan(
        candidate_id=value.candidate_id, target=value.target,
        baseline_version=value.baseline_version, challenger_version=value.challenger_version,
        hypothesis=value.hypothesis, evidence_case_ids=value.evidence_case_ids,
        subject=value.subject, known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if rebuilt.plan_id != value.plan_id or rebuilt.content_sha256 != value.content_sha256:
        raise ProductionHandoffError("調査計画の整合性を確認できません")


def _verify_candidate(value) -> None:
    rebuilt = build_learning_candidate(
        review_id=value.review_id, candidate_type=value.candidate_type,
        evidence_count=value.evidence_count, impact_quantity=value.impact_quantity,
        reason_codes=value.reason_codes, evidence_case_ids=value.evidence_case_ids,
    )
    if rebuilt.candidate_id != value.candidate_id or rebuilt.content_sha256 != value.content_sha256:
        raise ProductionHandoffError("改善候補の整合性を確認できません")


def _verify_candidate_decision(value) -> None:
    rebuilt = build_learning_candidate_decision_event(
        candidate_id=value.candidate_id, expected_revision=value.revision - 1,
        decision=value.decision, subject=value.subject, reason=value.reason,
        known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if (
        rebuilt.decision_event_id != value.decision_event_id
        or rebuilt.content_sha256 != value.content_sha256
    ):
        raise ProductionHandoffError("改善候補の判断履歴の整合性を確認できません")


def _verify_run(value) -> None:
    rebuilt = build_experiment_run(
        plan_id=value.plan_id, result_version=value.result_version,
        source_sha256=value.source_sha256, report=value.report, subject=value.subject,
        known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if rebuilt.run_id != value.run_id or rebuilt.content_sha256 != value.content_sha256:
        raise ProductionHandoffError("比較runの整合性を確認できません")


def _verify_decision(value) -> None:
    rebuilt = build_experiment_decision_event(
        run_id=value.run_id, expected_revision=value.revision - 1,
        decision=value.decision, subject=value.subject, reason=value.reason,
        known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if (
        rebuilt.decision_event_id != value.decision_event_id
        or rebuilt.content_sha256 != value.content_sha256
    ):
        raise ProductionHandoffError("比較run判断履歴の整合性を確認できません")


def _text(value, label: str, maximum: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise ProductionHandoffError(f"{label}は1〜{maximum}文字です")
    return result


def _datetime(value, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductionHandoffError(f"{label}はtimezone付きISO日時です") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ProductionHandoffError(f"{label}はtimezone付きISO日時です")
    return result.astimezone(UTC)
