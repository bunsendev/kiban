"""レビュー対応タスクを認証主体と版番号で管理する。"""

from __future__ import annotations

from dataclasses import asdict

from .actions import ActionConflict, is_overdue, make_review_action, make_review_action_event


class ReviewNotFound(KeyError):
    pass


class ReviewActionNotFound(KeyError):
    pass


class ReviewActionService:
    def __init__(self, review_store, action_store) -> None:
        self.review_store = review_store
        self.action_store = action_store

    def create(self, request, actor: str):
        if self.review_store.get(request.review_id) is None:
            raise ReviewNotFound(request.review_id)
        task, event = make_review_action(
            request.review_id,
            request.action_type,
            request.title,
            request.assignee,
            request.due_date,
            request.note,
            actor,
        )
        return self.action_store.create(task, event)

    def append(self, action_id: str, request, actor: str):
        current = self.action_store.get(action_id)
        if current is None:
            raise ReviewActionNotFound(action_id)
        if current.latest.revision != request.expected_revision:
            raise ActionConflict("ほかの利用者が先に更新しました。再読み込みしてください")
        event = make_review_action_event(
            action_id,
            request.expected_revision + 1,
            request.status,
            request.assignee,
            request.due_date,
            request.note,
            request.completion_evidence,
            actor,
            current.latest.status,
        )
        return self.action_store.append(event, request.expected_revision)

    def list(self, *, review_id: str | None = None, limit: int = 200) -> list[dict]:
        items = self.action_store.list_tasks(review_id=review_id, limit=limit)
        return [_snapshot_dict(item) for item in items]

    def list_events(self, *, action_id: str | None = None, limit: int = 500) -> list[dict]:
        items = self.action_store.list_events(action_id=action_id, limit=limit)
        return [asdict(item) for item in items]


def _snapshot_dict(snapshot) -> dict:
    value = asdict(snapshot.task)
    value.update(asdict(snapshot.latest))
    value["event_count"] = snapshot.event_count
    value["overdue"] = is_overdue(snapshot.latest)
    return value
