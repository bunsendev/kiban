"""Portable adapter for audited formal change proposals after SHADOW comparison."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from forecast_provider.field_learning import (
    FieldLearningConflict,
    FormalChangeDecision,
    FormalChangeTarget,
    LearningExperimentDecision,
    LearningExperimentTarget,
    SqliteFieldLearningStore,
    build_experiment_decision_event,
    build_experiment_plan,
    build_experiment_run,
    build_formal_change_decision_event,
    build_formal_change_proposal,
)

from .learning_reviews import LearningReviewConflict
from .production_handoff import ProductionHandoffError

_ALLOWED_TARGETS = {
    LearningExperimentTarget.DEMAND_FORECAST: {
        FormalChangeTarget.FORECAST_MODEL,
        FormalChangeTarget.FORECAST_FEATURE,
        FormalChangeTarget.DATA_CONTRACT,
    },
    LearningExperimentTarget.SHIPMENT_RECOMMENDATION: {
        FormalChangeTarget.SHIPMENT_POLICY,
        FormalChangeTarget.ROUTE_POLICY,
        FormalChangeTarget.DATA_CONTRACT,
    },
}


class PortableFormalChanges:
    def __init__(self, database: Path) -> None:
        self.store = SqliteFieldLearningStore(database)

    def overview(self) -> dict:
        eligible = []
        for plan in self.store.list_experiment_plans():
            _verify_plan(plan)
            for run in self.store.list_experiment_runs(plan.plan_id):
                _verify_run(run)
                decisions = self.store.list_experiment_decisions(run.run_id)
                for event in decisions:
                    _verify_experiment_decision(event)
                if (
                    decisions
                    and decisions[-1].decision
                    is LearningExperimentDecision.RECOMMEND_FORMAL_CHANGE
                ):
                    eligible.append({
                        "run_id": run.run_id,
                        "plan_id": plan.plan_id,
                        "target": plan.target.value,
                        "baseline_version": plan.baseline_version,
                        "challenger_version": plan.challenger_version,
                        "comparable_count": run.report["coverage"]["comparable_count"],
                        "source_decision_revision": decisions[-1].revision,
                    })
        return {
            "mode": "SHADOW",
            "eligible_runs": eligible,
            "proposals": [
                self._proposal_summary(value)
                for value in self.store.list_formal_change_proposals()
            ],
            "notice": "承認しても正式設定・モデル・policyには自動適用されません。",
        }

    def create_proposal(self, payload: dict) -> dict:
        run_id = _text(payload.get("run_id"), "比較run", 200)
        run, plan, source_decision = self._eligible_source(run_id)
        try:
            target = FormalChangeTarget(str(payload.get("change_target") or ""))
        except ValueError as exc:
            raise ProductionHandoffError("変更対象を選択してください") from exc
        if target not in _ALLOWED_TARGETS[plan.target]:
            raise ProductionHandoffError("比較対象と正式変更対象の組み合わせが不正です")
        known_at = _datetime(payload.get("known_at"), "提案基準日時")
        if known_at < source_decision.known_at:
            raise ProductionHandoffError("提案基準日時は比較判断日時以降です")
        if payload.get("confirm_no_automatic_application") is not True:
            raise ProductionHandoffError("設定へ自動適用しないことを確認してください")
        try:
            proposal = build_formal_change_proposal(
                run_id=run.run_id,
                source_decision_revision=source_decision.revision,
                change_target=target,
                current_configuration=_object(payload.get("current_configuration"), "現行設定"),
                proposed_configuration=_object(payload.get("proposed_configuration"), "変更後設定"),
                application_scope=_object(payload.get("application_scope"), "適用範囲"),
                acceptance_criteria=_statements(payload.get("acceptance_criteria"), "受入基準"),
                rollback_conditions=_statements(payload.get("rollback_conditions"), "rollback条件"),
                rollback_target_version=_text(
                    payload.get("rollback_target_version"), "rollback先版", 100
                ),
                author=_text(payload.get("author"), "作成者", 100),
                known_at=known_at,
                recorded_at=datetime.now(UTC),
            )
            self.store.put_formal_change_proposal(proposal)
        except ValueError as exc:
            raise ProductionHandoffError(str(exc)) from exc
        return self.view_proposal(proposal.proposal_id)

    def view_proposal(self, proposal_id: str) -> dict:
        proposal = self.store.get_formal_change_proposal(proposal_id)
        if proposal is None:
            raise ProductionHandoffError("正式変更案が見つかりません")
        _verify_proposal(proposal)
        run = self.store.get_experiment_run(proposal.run_id)
        if run is None:
            raise ProductionHandoffError("比較runが見つかりません")
        plan = self.store.get_experiment_plan(run.plan_id)
        if plan is None:
            raise ProductionHandoffError("比較計画が見つかりません")
        decisions = self.store.list_formal_change_decisions(proposal.proposal_id)
        for event in decisions:
            _verify_formal_decision(event)
        latest = decisions[-1] if decisions else None
        return {
            **self._proposal_summary(proposal),
            "source": {
                "plan_id": plan.plan_id,
                "target": plan.target.value,
                "baseline_version": plan.baseline_version,
                "challenger_version": plan.challenger_version,
                "result_version": run.result_version,
                "comparable_count": run.report["coverage"]["comparable_count"],
            },
            "current_configuration": proposal.current_configuration,
            "proposed_configuration": proposal.proposed_configuration,
            "application_scope": proposal.application_scope,
            "acceptance_criteria": list(proposal.acceptance_criteria),
            "rollback_conditions": list(proposal.rollback_conditions),
            "rollback_target_version": proposal.rollback_target_version,
            "author": proposal.author,
            "known_at": proposal.known_at.isoformat(),
            "recorded_at": proposal.recorded_at.isoformat(),
            "content_sha256": proposal.content_sha256,
            "status": "PENDING" if latest is None else latest.decision.value,
            "revision": 0 if latest is None else latest.revision,
            "application_status": "NOT_APPLIED",
            "decision_history": [
                {
                    "decision_event_id": value.decision_event_id,
                    "revision": value.revision,
                    "decision": value.decision.value,
                    "approver": value.approver,
                    "reason": value.reason,
                    "known_at": value.known_at.isoformat(),
                    "recorded_at": value.recorded_at.isoformat(),
                }
                for value in decisions
            ],
        }

    def decide(self, proposal_id: str, payload: dict) -> dict:
        proposal = self.store.get_formal_change_proposal(proposal_id)
        if proposal is None:
            raise ProductionHandoffError("正式変更案が見つかりません")
        _verify_proposal(proposal)
        expected = payload.get("expected_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ProductionHandoffError("expected_revisionは0以上の整数です")
        try:
            decision = FormalChangeDecision(str(payload.get("decision") or ""))
        except ValueError as exc:
            raise ProductionHandoffError("承認または却下を選択してください") from exc
        approver = _text(payload.get("approver"), "承認者", 100)
        if approver == proposal.author:
            raise ProductionHandoffError("作成者とは別の担当者が判断してください")
        self._eligible_source(proposal.run_id, proposal.source_decision_revision)
        if payload.get("confirm_separate_approval") is not True:
            raise ProductionHandoffError("別承認であり自動適用しないことを確認してください")
        reason = _text(payload.get("reason"), "判断理由", 500)
        now = datetime.now(UTC)
        try:
            event = build_formal_change_decision_event(
                proposal_id=proposal.proposal_id,
                expected_revision=expected,
                decision=decision,
                approver=approver,
                reason=reason,
                known_at=now,
                recorded_at=now,
            )
            self.store.append_formal_change_decision(event, expected)
        except FieldLearningConflict as exc:
            events = self.store.list_formal_change_decisions(proposal.proposal_id)
            latest = events[-1] if events else None
            if not (
                latest and latest.revision == expected + 1 and latest.decision is decision
                and latest.approver == approver and latest.reason == reason
            ):
                raise LearningReviewConflict(str(exc)) from exc
        return self.view_proposal(proposal.proposal_id)

    def _eligible_source(self, run_id: str, revision: int | None = None):
        run = self.store.get_experiment_run(run_id)
        if run is None:
            raise ProductionHandoffError("比較runが見つかりません")
        _verify_run(run)
        plan = self.store.get_experiment_plan(run.plan_id)
        if plan is None:
            raise ProductionHandoffError("比較計画が見つかりません")
        _verify_plan(plan)
        decisions = self.store.list_experiment_decisions(run_id)
        for event in decisions:
            _verify_experiment_decision(event)
        if (
            not decisions
            or decisions[-1].decision
            is not LearningExperimentDecision.RECOMMEND_FORMAL_CHANGE
        ):
            raise ProductionHandoffError("正式変更案の作成推奨が有効な比較runだけを選択できます")
        if revision is not None and decisions[-1].revision != revision:
            raise ProductionHandoffError("比較runの判断が更新されたため変更案を再確認してください")
        return run, plan, decisions[-1]

    @staticmethod
    def _proposal_summary(proposal) -> dict:
        return {
            "proposal_id": proposal.proposal_id,
            "run_id": proposal.run_id,
            "change_target": proposal.change_target.value,
            "source_decision_revision": proposal.source_decision_revision,
            "author": proposal.author,
        }


def _verify_plan(value) -> None:
    rebuilt = build_experiment_plan(
        candidate_id=value.candidate_id, target=value.target,
        baseline_version=value.baseline_version, challenger_version=value.challenger_version,
        hypothesis=value.hypothesis, evidence_case_ids=value.evidence_case_ids,
        subject=value.subject, known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if rebuilt.plan_id != value.plan_id or rebuilt.content_sha256 != value.content_sha256:
        raise ProductionHandoffError("比較計画の整合性を確認できません")


def _verify_run(value) -> None:
    rebuilt = build_experiment_run(
        plan_id=value.plan_id, result_version=value.result_version,
        source_sha256=value.source_sha256, report=value.report, subject=value.subject,
        known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if rebuilt.run_id != value.run_id or rebuilt.content_sha256 != value.content_sha256:
        raise ProductionHandoffError("比較runの整合性を確認できません")


def _verify_experiment_decision(value) -> None:
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


def _verify_proposal(value) -> None:
    rebuilt = build_formal_change_proposal(
        run_id=value.run_id, source_decision_revision=value.source_decision_revision,
        change_target=value.change_target, current_configuration=value.current_configuration,
        proposed_configuration=value.proposed_configuration,
        application_scope=value.application_scope,
        acceptance_criteria=value.acceptance_criteria,
        rollback_conditions=value.rollback_conditions,
        rollback_target_version=value.rollback_target_version, author=value.author,
        known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if rebuilt.proposal_id != value.proposal_id or rebuilt.content_sha256 != value.content_sha256:
        raise ProductionHandoffError("正式変更案の整合性を確認できません")


def _verify_formal_decision(value) -> None:
    rebuilt = build_formal_change_decision_event(
        proposal_id=value.proposal_id, expected_revision=value.revision - 1,
        decision=value.decision, approver=value.approver, reason=value.reason,
        known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if (
        rebuilt.decision_event_id != value.decision_event_id
        or rebuilt.content_sha256 != value.content_sha256
    ):
        raise ProductionHandoffError("正式変更案判断履歴の整合性を確認できません")


def _object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise ProductionHandoffError(f"{label}はJSON objectです")
    return value


def _statements(value, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProductionHandoffError(f"{label}は一覧です")
    return tuple(str(item).strip() for item in value)


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
