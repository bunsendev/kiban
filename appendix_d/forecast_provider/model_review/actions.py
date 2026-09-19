"""精度変化レビューに対する対応タスクと追記イベント。"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

ActionType = Literal[
    "RETEST",
    "DATA_FIX",
    "BUSINESS_CONFIRMATION",
    "MODEL_REVIEW",
    "LIFECYCLE_TRIAL",
    "OTHER",
]
ActionStatus = Literal["OPEN", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"]

ACTION_TYPES = {
    "RETEST",
    "DATA_FIX",
    "BUSINESS_CONFIRMATION",
    "MODEL_REVIEW",
    "LIFECYCLE_TRIAL",
    "OTHER",
}
ACTION_STATUSES = {"OPEN", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"}
TERMINAL_STATUSES = {"COMPLETED", "CANCELLED"}
ALLOWED_TRANSITIONS = {
    "OPEN": {"OPEN", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"},
    "IN_PROGRESS": {"IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"},
    "BLOCKED": {"BLOCKED", "IN_PROGRESS", "COMPLETED", "CANCELLED"},
}


@dataclass(frozen=True)
class ReviewActionTask:
    action_id: str
    review_id: str
    action_type: ActionType
    title: str
    created_by: str
    created_at: str


@dataclass(frozen=True)
class ReviewActionEvent:
    event_id: str
    action_id: str
    revision: int
    status: ActionStatus
    assignee: str
    due_date: str
    note: str
    completion_evidence: str | None
    recorded_by: str
    recorded_at: str


@dataclass(frozen=True)
class ReviewActionSnapshot:
    task: ReviewActionTask
    latest: ReviewActionEvent
    event_count: int


class ActionConflict(ValueError):
    pass


def make_review_action(
    review_id: str,
    action_type: str,
    title: str,
    assignee: str,
    due_date: date,
    note: str,
    created_by: str,
) -> tuple[ReviewActionTask, ReviewActionEvent]:
    _required(
        review_id=review_id,
        title=title,
        assignee=assignee,
        note=note,
        created_by=created_by,
    )
    if action_type not in ACTION_TYPES:
        raise ValueError("action_typeが不正です")
    action_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    task = ReviewActionTask(action_id, review_id, action_type, title, created_by, now)
    event = make_review_action_event(
        action_id=action_id,
        revision=1,
        status="OPEN",
        assignee=assignee,
        due_date=due_date,
        note=note,
        completion_evidence=None,
        recorded_by=created_by,
        previous_status=None,
    )
    return task, event


def make_review_action_event(
    action_id: str,
    revision: int,
    status: str,
    assignee: str,
    due_date: date,
    note: str,
    completion_evidence: str | None,
    recorded_by: str,
    previous_status: str | None,
) -> ReviewActionEvent:
    _required(action_id=action_id, assignee=assignee, note=note, recorded_by=recorded_by)
    if isinstance(revision, bool) or revision < 1:
        raise ValueError("revisionは1以上です")
    if status not in ACTION_STATUSES:
        raise ValueError("statusが不正です")
    validate_action_transition(previous_status, status)
    if status == "COMPLETED" and (
        not isinstance(completion_evidence, str) or not completion_evidence.strip()
    ):
        raise ValueError("完了時はcompletion_evidenceが必要です")
    if status != "COMPLETED" and completion_evidence is not None:
        raise ValueError("completion_evidenceは完了時だけ記録できます")
    return ReviewActionEvent(
        event_id=str(uuid.uuid4()),
        action_id=action_id,
        revision=revision,
        status=status,
        assignee=assignee,
        due_date=due_date.isoformat(),
        note=note,
        completion_evidence=completion_evidence,
        recorded_by=recorded_by,
        recorded_at=datetime.now(UTC).isoformat(),
    )


def validate_action_transition(previous_status: str | None, status: str) -> None:
    if previous_status is None:
        if status != "OPEN":
            raise ActionConflict("最初の対応状態はOPENです")
        return
    if previous_status in TERMINAL_STATUSES:
        raise ActionConflict("完了または中止した対応タスクは変更できません")
    if status not in ALLOWED_TRANSITIONS[previous_status]:
        raise ActionConflict(f"{previous_status}から{status}へ変更できません")


def is_overdue(event: ReviewActionEvent, today: date | None = None) -> bool:
    reference = today or datetime.now(UTC).date()
    return event.status not in TERMINAL_STATUSES and date.fromisoformat(event.due_date) < reference


def _required(**values) -> None:
    empty = [
        name
        for name, value in values.items()
        if not isinstance(value, str) or not value.strip()
    ]
    if empty:
        raise ValueError(f"必須項目が空です: {', '.join(empty)}")
