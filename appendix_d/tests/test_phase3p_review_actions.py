"""Phase 3P: 精度変化レビュー後の対応タスク台帳。"""

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from forecast_provider.api.authentication import Authorizer, TokenAuthenticator
from forecast_provider.api.model_review_action_routes import install_model_review_action_routes
from forecast_provider.api.model_review_action_schemas import (
    ReviewActionCreate,
    ReviewActionEventCreate,
)
from forecast_provider.model_review import (
    ActionConflict,
    ReviewActionService,
    SqliteModelReviewStore,
    SqliteReviewActionStore,
    make_model_drift_review,
    make_review_action,
    make_review_action_event,
)

PROFILE_ID = "a" * 64


def _stores(tmp_path):
    path = tmp_path / "review.sqlite3"
    reviews = SqliteModelReviewStore(path)
    review = make_model_drift_review(
        PROFILE_ID,
        "review-v1",
        "MODEL_ISSUE",
        "reviewer",
        "精度低下を確認",
        "追加テストする",
        {"comparison_profile_id": PROFILE_ID, "direction": "WAPE_UP"},
    )
    reviews.put(review)
    return reviews, SqliteReviewActionStore(path), review


def _create(review_id: str, *, due_date: date | None = None) -> ReviewActionCreate:
    return ReviewActionCreate(
        review_id=review_id,
        action_type="RETEST",
        title="期間を変えて再テスト",
        assignee="forecast-team",
        due_date=due_date or date.today() + timedelta(days=7),
        note="直近90日でも比較する",
    )


def _event(revision: int, status: str = "IN_PROGRESS", **values) -> ReviewActionEventCreate:
    return ReviewActionEventCreate(
        expected_revision=revision,
        status=status,
        assignee=values.get("assignee", "forecast-team"),
        due_date=values.get("due_date", date.today() + timedelta(days=7)),
        note=values.get("note", "再テストを開始した"),
        completion_evidence=values.get("completion_evidence"),
    )


def test_action_store_preserves_assignment_and_deadline_history(tmp_path) -> None:
    reviews, actions, review = _stores(tmp_path)
    service = ReviewActionService(reviews, actions)
    created = service.create(_create(review.review_id), "creator")

    updated = service.append(
        created.task.action_id,
        _event(1, assignee="analyst", due_date=date.today() + timedelta(days=10)),
        "manager",
    )

    assert updated.latest.revision == 2
    assert updated.latest.assignee == "analyst"
    history = actions.list_events(action_id=created.task.action_id)
    assert [item.revision for item in history] == [2, 1]
    assert history[0].recorded_by == "manager"
    assert history[1].recorded_by == "creator"


def test_action_revision_conflict_and_terminal_state_are_enforced(tmp_path) -> None:
    reviews, actions, review = _stores(tmp_path)
    service = ReviewActionService(reviews, actions)
    created = service.create(_create(review.review_id), "creator")
    service.append(
        created.task.action_id,
        _event(1, "COMPLETED", completion_evidence="run-123の結果を確認"),
        "reviewer",
    )

    with pytest.raises(ActionConflict, match="完了または中止"):
        service.append(created.task.action_id, _event(2), "reviewer")
    with pytest.raises(ActionConflict, match="先に更新"):
        actions.append(
            make_review_action_event(
                created.task.action_id,
                2,
                "IN_PROGRESS",
                "analyst",
                date.today(),
                "古い画面から更新",
                None,
                "reviewer",
                "OPEN",
            ),
            1,
        )


def test_overdue_is_derived_without_changing_history(tmp_path) -> None:
    reviews, actions, review = _stores(tmp_path)
    service = ReviewActionService(reviews, actions)
    created = service.create(
        _create(review.review_id, due_date=date.today() - timedelta(days=1)), "creator"
    )

    assert service.list()[0]["overdue"] is True
    service.append(
        created.task.action_id,
        _event(1, "COMPLETED", completion_evidence="結果ファイルを保存"),
        "reviewer",
    )
    assert service.list()[0]["overdue"] is False


def test_review_action_api_requires_auth_and_records_authenticated_actor(tmp_path) -> None:
    reviews, actions, review = _stores(tmp_path)
    app = FastAPI()
    install_model_review_action_routes(
        app,
        Authorizer(TokenAuthenticator.single("token", "api-reviewer")),
        ReviewActionService(reviews, actions),
    )
    api = TestClient(app)
    payload = _create(review.review_id).model_dump(mode="json")

    assert api.post("/api/model-drift-review-actions", json=payload).status_code == 401
    api.headers["Authorization"] = "Bearer token"
    created = api.post("/api/model-drift-review-actions", json=payload)
    assert created.status_code == 201, created.text
    action_id = created.json()["id"]
    result = api.get("/api/model-drift-review-actions").json()[0]
    assert result["created_by"] == "api-reviewer"
    assert result["event_count"] == 1

    completed = _event(
        1, "COMPLETED", completion_evidence="comparison-1を再確認"
    ).model_dump(mode="json")
    response = api.post(
        f"/api/model-drift-review-actions/{action_id}/events", json=completed
    )
    assert response.status_code == 200, response.text
    events = api.get(
        f"/api/model-drift-review-action-events?action_id={action_id}"
    ).json()
    assert events[0]["recorded_by"] == "api-reviewer"
    assert events[0]["completion_evidence"] == "comparison-1を再確認"


def test_domain_requires_completion_evidence() -> None:
    task, _event_value = make_review_action(
        "review-id", "RETEST", "再テスト", "analyst", date.today(), "確認する", "creator"
    )
    with pytest.raises(ValueError, match="completion_evidence"):
        make_review_action_event(
            task.action_id,
            2,
            "COMPLETED",
            "analyst",
            date.today(),
            "完了",
            None,
            "reviewer",
            "OPEN",
        )
