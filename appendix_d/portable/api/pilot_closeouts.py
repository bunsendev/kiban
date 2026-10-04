"""Bind a verified Pilot evaluation decision to an audited application transition."""

from __future__ import annotations

from .change_applications import PortableChangeApplications
from .learning_reviews import LearningReviewConflict
from .pilot_evaluation_gates import PILOT_EVALUATION_LOCK, PortablePilotEvaluationGates
from .production_handoff import ProductionHandoffError

REFERENCE_FORMAT = "portable-pilot-closeout-reference-v1"


class PortablePilotCloseouts:
    def __init__(self, paths) -> None:
        self.gates = PortablePilotEvaluationGates(paths)
        self.applications = PortableChangeApplications(
            paths.state / "shipment-actual-outcomes.sqlite3"
        )

    def view(self, assessment_id: str) -> dict:
        assessment = self.gates.view(assessment_id)
        application = self.applications.view_application(assessment["application_id"])
        decision = assessment["decisions"][-1] if assessment["decisions"] else None
        action = _action(assessment, application, decision)
        return {
            "mode": "SHADOW",
            "assessment_id": assessment_id,
            "assessment_content_sha256": assessment["content_sha256"],
            "assessment_revision": assessment["revision"],
            "assessment_status": assessment["report"]["status"],
            "policy_version": assessment["policy"]["policy_version"],
            "runtime_evaluation_id": assessment["runtime_evaluation_id"],
            "runtime_evaluation_sha256": assessment["runtime_evaluation_sha256"],
            "latest_decision": decision,
            "application": application,
            "action": action,
            "notice": ("担当者確認を省略せず、正式設定、受入、rollbackを自動実行しません。"),
        }

    def accept(self, assessment_id: str, payload: dict) -> dict:
        with PILOT_EVALUATION_LOCK:
            view = self.view(assessment_id)
            _expected_assessment_revision(payload, view)
            if view["action"] != "EVALUATE_ACCEPTANCE":
                raise ProductionHandoffError(
                    "合格済み評価の正式採用審査送付判断が最新である場合だけ受入評価できます"
                )
            return self.applications.evaluate_acceptance(
                view["application"]["application_id"],
                payload,
                pilot_evaluation_reference=_reference(view),
            )

    def rollback(self, assessment_id: str, payload: dict) -> dict:
        with PILOT_EVALUATION_LOCK:
            view = self.view(assessment_id)
            _expected_assessment_revision(payload, view)
            if view["action"] != "EVALUATE_ROLLBACK":
                raise ProductionHandoffError(
                    "Baselineへ戻す判断または同じ評価による受入未達後だけrollbackを検証できます"
                )
            return self.applications.evaluate_rollback(
                view["application"]["application_id"],
                payload,
                pilot_evaluation_reference=_reference(view),
            )

    def pause(self, assessment_id: str, payload: dict) -> dict:
        with PILOT_EVALUATION_LOCK:
            view = self.view(assessment_id)
            _expected_assessment_revision(payload, view)
            if view["action"] != "CONFIRM_PAUSE":
                raise ProductionHandoffError(
                    "最新の担当者判断がPilot一時停止の場合だけ停止を確定できます"
                )
            return self.applications.pause_pilot(
                view["application"]["application_id"],
                payload,
                pilot_evaluation_reference=_reference(view),
            )


def _action(assessment: dict, application: dict, decision: dict | None) -> str:
    if decision is None:
        return "RECORD_DECISION"
    state = application["state"]
    selected = decision["decision"]
    if (
        state == "PILOT_ACTIVE"
        and assessment["report"]["status"] == "PASSED"
        and selected == "FORWARD_TO_ACCEPTANCE"
    ):
        return "EVALUATE_ACCEPTANCE"
    if state == "PILOT_ACTIVE" and selected == "REQUEST_ROLLBACK":
        return "EVALUATE_ROLLBACK"
    if state == "PILOT_ACTIVE" and selected == "PAUSE_PILOT":
        return "CONFIRM_PAUSE"
    if state == "ROLLBACK_REQUIRED" and _linked_to_assessment(application, assessment):
        return "EVALUATE_ROLLBACK"
    if state in {"PAUSED", "ACCEPTED", "ROLLED_BACK"}:
        return "COMPLETE"
    return "NO_TRANSITION"


def _linked_to_assessment(application: dict, assessment: dict) -> bool:
    if not application["events"]:
        return False
    reference = application["events"][-1]["evidence"].get("pilot_evaluation_reference")
    decision = assessment["decisions"][-1] if assessment["decisions"] else None
    return (
        isinstance(reference, dict)
        and decision is not None
        and reference.get("assessment_id") == assessment["assessment_id"]
        and reference.get("assessment_content_sha256") == assessment["content_sha256"]
        and reference.get("decision_id") == decision["decision_id"]
        and reference.get("decision_content_sha256") == decision["content_sha256"]
    )


def _expected_assessment_revision(payload: dict, view: dict) -> None:
    expected = payload.get("expected_assessment_revision")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise ProductionHandoffError("expected_assessment_revisionは1以上の整数です")
    if expected != view["assessment_revision"]:
        raise LearningReviewConflict("Pilot評価判断が更新されています。再読み込みしてください")


def _reference(view: dict) -> dict:
    decision = view["latest_decision"]
    verified = view["application"]
    gate = {
        "format": REFERENCE_FORMAT,
        "assessment_id": view["assessment_id"],
        "assessment_content_sha256": view["assessment_content_sha256"],
        "assessment_revision": view["assessment_revision"],
        "assessment_status": view["assessment_status"],
        "policy_version": view["policy_version"],
        "runtime_evaluation_id": view["runtime_evaluation_id"],
        "runtime_evaluation_sha256": view["runtime_evaluation_sha256"],
        "decision_id": decision["decision_id"],
        "decision_content_sha256": decision["content_sha256"],
        "decision_revision": decision["revision"],
        "decision": decision["decision"],
        "application_id": verified["application_id"],
        "application_revision": verified["revision"],
    }
    return gate
