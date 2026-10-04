"""Audited Pilot application gate for independently approved formal changes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from forecast_provider.field_learning import (
    ChangeApplicationState,
    ChangeApplicationTransition,
    FieldLearningConflict,
    FormalChangeDecision,
    SqliteFieldLearningStore,
    build_change_application,
    build_change_application_event,
)

from .formal_changes import PortableFormalChanges, _verify_formal_decision, _verify_proposal
from .learning_reviews import LearningReviewConflict
from .production_handoff import ProductionHandoffError


class PortableChangeApplications:
    def __init__(self, database: Path) -> None:
        self.store = SqliteFieldLearningStore(database)
        self.formal_changes = PortableFormalChanges(database)

    def overview(self) -> dict:
        eligible = []
        for proposal in self.store.list_formal_change_proposals():
            try:
                _, decision = self._approved_proposal(proposal.proposal_id)
            except ProductionHandoffError:
                continue
            eligible.append({
                "proposal_id": proposal.proposal_id,
                "change_target": proposal.change_target.value,
                "candidate_version_default": _configuration_version(
                    proposal.proposed_configuration
                ),
                "application_scope": proposal.application_scope,
                "approval_revision": decision.revision,
                "approver": decision.approver,
            })
        applications = [
            self._application_summary(item)
            for item in self.store.list_change_applications()
        ]
        return {
            "mode": "SHADOW",
            "eligible_proposals": eligible,
            "applications": applications,
            "active_assignments": [
                item for item in applications
                if item["state"] in {
                    ChangeApplicationState.PILOT_ACTIVE.value,
                    ChangeApplicationState.ACCEPTED.value,
                }
            ],
            "notice": (
                "Pilot適用記録は対象範囲の利用許可です。正式設定や現場全体へ"
                "自動反映せず、受入未達時はrollbackを完了してください。"
            ),
        }

    def create_application(self, payload: dict) -> dict:
        proposal_id = _text(payload.get("proposal_id"), "正式変更案", 200)
        proposal, decision = self._approved_proposal(proposal_id)
        known_at = _datetime(payload.get("known_at"), "準備基準日時")
        if known_at < decision.known_at:
            raise ProductionHandoffError("準備基準日時は変更案の承認日時以降です")
        if payload.get("confirm_pilot_only") is not True:
            raise ProductionHandoffError("Pilot Scope限定であることを確認してください")
        candidate_version = _text(payload.get("candidate_version"), "候補版", 100)
        if candidate_version == proposal.rollback_target_version:
            raise ProductionHandoffError("候補版はrollback先版と異なる版にしてください")
        try:
            application = build_change_application(
                proposal_id=proposal.proposal_id,
                source_proposal_decision_revision=decision.revision,
                candidate_version=candidate_version,
                application_scope=proposal.application_scope,
                backup_reference=_text(
                    payload.get("backup_reference"), "事前backup参照", 300
                ),
                backup_sha256=str(payload.get("backup_sha256") or ""),
                executor=_text(payload.get("executor"), "適用担当者", 100),
                known_at=known_at,
                recorded_at=datetime.now(UTC),
            )
            self.store.put_change_application(application)
        except ValueError as exc:
            raise ProductionHandoffError(str(exc)) from exc
        return self.view_application(application.application_id)

    def view_application(self, application_id: str) -> dict:
        application = self.store.get_change_application(application_id)
        if application is None:
            raise ProductionHandoffError("Pilot適用計画が見つかりません")
        _verify_application(application)
        proposal, decision = self._proposal_and_decision(application.proposal_id)
        events = self.store.list_change_application_events(application.application_id)
        for event in events:
            _verify_application_event(event)
        latest = events[-1] if events else None
        source_is_current = (
            decision is not None
            and decision.decision is FormalChangeDecision.APPROVED_FOR_IMPLEMENTATION
            and decision.revision == application.source_proposal_decision_revision
        )
        return {
            **self._application_summary(application, events),
            "source_approval_is_current": source_is_current,
            "proposal": {
                "proposal_id": proposal.proposal_id,
                "change_target": proposal.change_target.value,
                "proposed_configuration": proposal.proposed_configuration,
                "acceptance_criteria": list(proposal.acceptance_criteria),
                "rollback_conditions": list(proposal.rollback_conditions),
                "rollback_target_version": proposal.rollback_target_version,
            },
            "application_scope": application.application_scope,
            "backup_reference": application.backup_reference,
            "backup_sha256": application.backup_sha256,
            "executor": application.executor,
            "known_at": application.known_at.isoformat(),
            "recorded_at": application.recorded_at.isoformat(),
            "content_sha256": application.content_sha256,
            "events": [_event_view(item) for item in events],
            "next_action": _next_action(
                ChangeApplicationState.PREPARED if latest is None else latest.resulting_state
            ),
        }

    def evaluate_gate(self, application_id: str, payload: dict) -> dict:
        application, _, state, revision = self._mutable(application_id, payload)
        if state not in {ChangeApplicationState.PREPARED, ChangeApplicationState.BLOCKED}:
            raise ProductionHandoffError("Pilot開始Gateを評価できる状態ではありません")
        checks = _checks(payload.get("smoke_checks"), "smoke test")
        backup_verified = payload.get("backup_verified") is True
        candidate_staged = payload.get("candidate_staged") is True
        candidate_manifest_sha256 = _sha256(
            payload.get("candidate_manifest_sha256"), "候補版manifest"
        )
        passed = backup_verified and candidate_staged and all(
            item["passed"] for item in checks
        )
        evidence = {
            "backup_reference": application.backup_reference,
            "backup_sha256": application.backup_sha256,
            "backup_verified": backup_verified,
            "candidate_staged": candidate_staged,
            "candidate_version": application.candidate_version,
            "candidate_manifest_sha256": candidate_manifest_sha256,
            "smoke_checks": checks,
        }
        self._append_event(
            application, revision,
            ChangeApplicationTransition.PILOT_GATE_EVALUATED,
            ChangeApplicationState.PILOT_ACTIVE if passed else ChangeApplicationState.BLOCKED,
            payload, evidence,
        )
        return self.view_application(application.application_id)

    def evaluate_acceptance(self, application_id: str, payload: dict) -> dict:
        application, proposal, state, revision = self._mutable(application_id, payload)
        if state is not ChangeApplicationState.PILOT_ACTIVE:
            raise ProductionHandoffError("受入評価はPilot開始後に実施してください")
        acceptance = _matched_results(
            payload.get("acceptance_results"), proposal.acceptance_criteria,
            "受入基準", result_key="passed",
        )
        rollback = _matched_results(
            payload.get("rollback_results"), proposal.rollback_conditions,
            "rollback条件", result_key="triggered",
        )
        accepted = all(item["passed"] for item in acceptance) and not any(
            item["triggered"] for item in rollback
        )
        evidence = {
            "acceptance_results": acceptance,
            "rollback_results": rollback,
            "candidate_version": application.candidate_version,
        }
        self._append_event(
            application, revision,
            ChangeApplicationTransition.ACCEPTANCE_EVALUATED,
            ChangeApplicationState.ACCEPTED if accepted
            else ChangeApplicationState.ROLLBACK_REQUIRED,
            payload, evidence,
        )
        return self.view_application(application.application_id)

    def evaluate_rollback(self, application_id: str, payload: dict) -> dict:
        application, proposal, state, revision = self._mutable(application_id, payload)
        if state not in {
            ChangeApplicationState.PILOT_ACTIVE,
            ChangeApplicationState.ROLLBACK_REQUIRED,
        }:
            raise ProductionHandoffError("rollbackを評価できる状態ではありません")
        target = _text(payload.get("rollback_target_version"), "rollback先版", 100)
        if target != proposal.rollback_target_version:
            raise ProductionHandoffError("変更案で固定したrollback先版と一致しません")
        checks = _checks(payload.get("rollback_checks"), "rollback検査")
        restored = payload.get("backup_restored") is True
        passed = restored and all(item["passed"] for item in checks)
        evidence = {
            "backup_reference": application.backup_reference,
            "backup_sha256": application.backup_sha256,
            "backup_restored": restored,
            "rollback_target_version": target,
            "rollback_checks": checks,
        }
        self._append_event(
            application, revision,
            ChangeApplicationTransition.ROLLBACK_EVALUATED,
            ChangeApplicationState.ROLLED_BACK if passed
            else ChangeApplicationState.ROLLBACK_REQUIRED,
            payload, evidence,
        )
        return self.view_application(application.application_id)

    def _mutable(self, application_id: str, payload: dict):
        application = self.store.get_change_application(application_id)
        if application is None:
            raise ProductionHandoffError("Pilot適用計画が見つかりません")
        _verify_application(application)
        proposal, _ = self._approved_proposal(
            application.proposal_id, application.source_proposal_decision_revision
        )
        events = self.store.list_change_application_events(application_id)
        for event in events:
            _verify_application_event(event)
        revision = _expected_revision(payload.get("expected_revision"))
        current_revision = 0 if not events else events[-1].revision
        if revision != current_revision:
            raise LearningReviewConflict("Pilot適用状態が更新されています。再読み込みしてください")
        state = (
            ChangeApplicationState.PREPARED if not events else events[-1].resulting_state
        )
        return application, proposal, state, revision

    def _append_event(self, application, revision, transition, state, payload, evidence):
        actor = _text(payload.get("actor"), "実行担当者", 100)
        reason = _text(payload.get("reason"), "記録理由", 500)
        if payload.get("confirm_audited_transition") is not True:
            raise ProductionHandoffError("監査記録として追記することを確認してください")
        now = datetime.now(UTC)
        try:
            event = build_change_application_event(
                application_id=application.application_id,
                expected_revision=revision, transition=transition,
                resulting_state=state, actor=actor, reason=reason,
                evidence=evidence, known_at=now, recorded_at=now,
            )
            self.store.append_change_application_event(event, revision)
        except FieldLearningConflict as exc:
            events = self.store.list_change_application_events(application.application_id)
            latest = events[-1] if events else None
            if not (
                latest and latest.revision == revision + 1
                and latest.transition is transition and latest.resulting_state is state
                and latest.actor == actor and latest.reason == reason
                and latest.evidence == evidence
            ):
                raise LearningReviewConflict(str(exc)) from exc

    def _approved_proposal(self, proposal_id: str, revision: int | None = None):
        proposal, decision = self._proposal_and_decision(proposal_id)
        if (
            decision is None
            or decision.decision is not FormalChangeDecision.APPROVED_FOR_IMPLEMENTATION
        ):
            raise ProductionHandoffError("実装案として承認済みの正式変更案だけを選択できます")
        if revision is not None and decision.revision != revision:
            raise ProductionHandoffError("正式変更案の承認状態が更新されたため再確認してください")
        return proposal, decision

    def _proposal_and_decision(self, proposal_id: str):
        proposal = self.store.get_formal_change_proposal(proposal_id)
        if proposal is None:
            raise ProductionHandoffError("正式変更案が見つかりません")
        _verify_proposal(proposal)
        decisions = self.store.list_formal_change_decisions(proposal_id)
        for event in decisions:
            _verify_formal_decision(event)
        return proposal, decisions[-1] if decisions else None

    def _application_summary(self, application, events=None) -> dict:
        _verify_application(application)
        if events is None:
            events = self.store.list_change_application_events(application.application_id)
            for event in events:
                _verify_application_event(event)
        state = ChangeApplicationState.PREPARED if not events else events[-1].resulting_state
        return {
            "application_id": application.application_id,
            "proposal_id": application.proposal_id,
            "candidate_version": application.candidate_version,
            "state": state.value,
            "revision": 0 if not events else events[-1].revision,
            "application_scope": application.application_scope,
            "executor": application.executor,
        }


def _verify_application(value) -> None:
    rebuilt = build_change_application(
        proposal_id=value.proposal_id,
        source_proposal_decision_revision=value.source_proposal_decision_revision,
        candidate_version=value.candidate_version,
        application_scope=value.application_scope,
        backup_reference=value.backup_reference,
        backup_sha256=value.backup_sha256, executor=value.executor,
        known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if (
        rebuilt.application_id != value.application_id
        or rebuilt.content_sha256 != value.content_sha256
    ):
        raise ProductionHandoffError("Pilot適用計画の整合性を確認できません")


def _verify_application_event(value) -> None:
    rebuilt = build_change_application_event(
        application_id=value.application_id, expected_revision=value.revision - 1,
        transition=value.transition, resulting_state=value.resulting_state,
        actor=value.actor, reason=value.reason, evidence=value.evidence,
        known_at=value.known_at, recorded_at=value.recorded_at,
    )
    if rebuilt.event_id != value.event_id or rebuilt.content_sha256 != value.content_sha256:
        raise ProductionHandoffError("Pilot適用履歴の整合性を確認できません")


def _event_view(value) -> dict:
    return {
        "event_id": value.event_id,
        "revision": value.revision,
        "transition": value.transition.value,
        "resulting_state": value.resulting_state.value,
        "actor": value.actor,
        "reason": value.reason,
        "evidence": value.evidence,
        "known_at": value.known_at.isoformat(),
        "recorded_at": value.recorded_at.isoformat(),
    }


def _next_action(state: ChangeApplicationState) -> str:
    return {
        ChangeApplicationState.PREPARED: "EVALUATE_PILOT_GATE",
        ChangeApplicationState.BLOCKED: "FIX_AND_RETRY_PILOT_GATE",
        ChangeApplicationState.PILOT_ACTIVE: "EVALUATE_ACCEPTANCE_OR_ROLLBACK",
        ChangeApplicationState.ROLLBACK_REQUIRED: "COMPLETE_ROLLBACK",
        ChangeApplicationState.ACCEPTED: "COMPLETE",
        ChangeApplicationState.ROLLED_BACK: "COMPLETE",
    }[state]


def _configuration_version(value: dict) -> str:
    version = value.get("version") if isinstance(value, dict) else None
    return str(version or "candidate-v1")[:100]


def _checks(value, label: str) -> list[dict]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ProductionHandoffError(f"{label}は1〜20件です")
    result = []
    names = set()
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("passed"), bool):
            raise ProductionHandoffError(f"{label}の結果を確認してください")
        name = _text(item.get("name"), f"{label}名", 200)
        if name in names:
            raise ProductionHandoffError(f"{label}名は重複できません")
        names.add(name)
        result.append({
            "name": name,
            "passed": item["passed"],
            "evidence": _text(item.get("evidence"), f"{label}根拠", 500),
        })
    return result


def _matched_results(value, expected, label: str, *, result_key: str) -> list[dict]:
    if not isinstance(value, list) or len(value) != len(expected):
        raise ProductionHandoffError(f"{label}を全件評価してください")
    result = []
    for item, statement in zip(value, expected, strict=True):
        if not isinstance(item, dict) or item.get("statement") != statement:
            raise ProductionHandoffError(f"{label}の順序または内容が変更されています")
        if not isinstance(item.get(result_key), bool):
            raise ProductionHandoffError(f"{label}の判定を確認してください")
        result.append({
            "statement": statement,
            result_key: item[result_key],
            "evidence": _text(item.get("evidence"), f"{label}根拠", 500),
        })
    return result


def _expected_revision(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProductionHandoffError("expected_revisionは0以上の整数です")
    return value


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


def _sha256(value, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(item not in "0123456789abcdef" for item in result):
        raise ProductionHandoffError(f"{label} SHA-256は64桁の16進数です")
    return result
