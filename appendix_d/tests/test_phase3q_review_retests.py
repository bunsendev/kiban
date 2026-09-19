"""Phase 3Q: レビュー対応からの追加テストと結果自動連携。"""

import sqlite3
from datetime import date

from fastapi.testclient import TestClient
from test_phase3i_comparison_campaign import _fixture, _request

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.comparison_campaign import SqliteComparisonCampaignStore
from forecast_provider.evaluation_registry import SqliteEvaluationRegistryStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.model_review import (
    ReviewRetestSynchronizer,
    SqliteModelReviewStore,
    SqliteReviewActionStore,
    SqliteReviewRetestStore,
    make_model_drift_review,
    make_review_action,
)
from forecast_provider.provider_conformance import SqliteConformanceJobStore

PROFILE_ID = "a" * 64


def _review_fixture(tmp_path, *, action_type="RETEST"):
    base_api, snapshot_id, database = _fixture(tmp_path)
    source = base_api.post(
        "/api/comparison-campaigns", json=_request(snapshot_id, "phase3q-source")
    ).json()
    source_comparison_id = "phase3q-source-comparison"
    _insert_comparison(database, source_comparison_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE comparison_campaign_finalizations SET status='SUCCEEDED',"
            "finished_at='2026-09-18T00:00:00+00:00',comparison_id=? "
            "WHERE campaign_id=?",
            (source_comparison_id, source["campaign_id"]),
        )
    runs = SqliteRunStore(database)
    catalog = SqliteCatalogStore(database)
    evaluations = SqliteEvaluationRegistryStore(database)
    jobs = SqliteConformanceJobStore(database)
    campaigns = SqliteComparisonCampaignStore(database)
    reviews = SqliteModelReviewStore(database)
    actions = SqliteReviewActionStore(database)
    retests = SqliteReviewRetestStore(database)
    review = make_model_drift_review(
        PROFILE_ID,
        "review-v1",
        "MODEL_ISSUE",
        "approver",
        "精度低下を確認",
        "追加テストする",
        {
            "comparison_profile_id": PROFILE_ID,
            "latest": {
                "campaign_id": source["campaign_id"],
                "comparison_id": source_comparison_id,
            },
        },
    )
    reviews.put(review)
    task, event = make_review_action(
        review.review_id,
        action_type,
        "期間を変えて再テスト",
        "analyst",
        date(2026, 12, 31),
        "別期間で確認する",
        "approver",
    )
    actions.create(task, event)
    api = TestClient(
        create_app(
            runs,
            catalog,
            "token",
            tmp_path,
            evaluation_registry=evaluations,
            conformance_jobs=jobs,
            comparison_campaigns=campaigns,
            model_reviews=reviews,
            review_actions=actions,
            review_retests=retests,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    return api, database, snapshot_id, task, actions, retests, campaigns


def _payload(snapshot_id: str, key: str = "phase3q-retest-001") -> dict:
    return {
        "request_key": key,
        "expected_revision": 1,
        "target_snapshot_id": snapshot_id,
    }


def test_retest_api_reuses_source_models_and_is_idempotent(tmp_path) -> None:
    api, _database, snapshot_id, task, actions, _retests, _campaigns = _review_fixture(
        tmp_path
    )

    first = api.post(
        f"/api/model-drift-review-actions/{task.action_id}/retests",
        json=_payload(snapshot_id),
    )
    second = api.post(
        f"/api/model-drift-review-actions/{task.action_id}/retests",
        json=_payload(snapshot_id),
    )

    assert first.status_code == second.status_code == 202
    assert first.json()["campaign_id"] == second.json()["campaign_id"]
    assert first.json()["source_campaign_id"] != first.json()["campaign_id"]
    assert first.json()["status"] == "RUNNING"
    assert actions.get(task.action_id).latest.status == "IN_PROGRESS"
    assert actions.get(task.action_id).event_count == 2
    listing = api.get("/api/model-drift-review-retests").json()
    assert listing[0]["requested_by"] == "local-admin"


def test_success_is_appended_with_campaign_and_comparison_evidence(tmp_path) -> None:
    api, database, snapshot_id, task, actions, retests, campaigns = _review_fixture(
        tmp_path
    )
    started = api.post(
        f"/api/model-drift-review-actions/{task.action_id}/retests",
        json=_payload(snapshot_id),
    ).json()
    comparison_id = "phase3q-comparison-success"
    _insert_comparison(database, comparison_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE comparison_campaign_finalizations SET status='SUCCEEDED',"
            "finished_at='2026-09-19T00:00:00+00:00',comparison_id=? "
            "WHERE campaign_id=?",
            (comparison_id, started["campaign_id"]),
        )

    synchronizer = ReviewRetestSynchronizer(retests, campaigns)
    assert synchronizer.sync_pending() == 1
    assert synchronizer.sync_pending() == 0
    current = actions.get(task.action_id)
    assert current.latest.status == "COMPLETED"
    assert comparison_id in current.latest.completion_evidence
    assert started["campaign_id"] in current.latest.completion_evidence
    assert current.latest.recorded_by == "system:comparison-campaign-worker"


def test_failure_is_appended_as_blocked_and_can_be_retried(tmp_path) -> None:
    api, database, snapshot_id, task, actions, retests, campaigns = _review_fixture(
        tmp_path
    )
    started = api.post(
        f"/api/model-drift-review-actions/{task.action_id}/retests",
        json=_payload(snapshot_id),
    ).json()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE comparison_campaign_finalizations SET status='FAILED',"
            "finished_at='2026-09-19T00:00:00+00:00',error_code='RunFailed',"
            "error_message='予測runを確認してください' WHERE campaign_id=?",
            (started["campaign_id"],),
        )
    assert ReviewRetestSynchronizer(retests, campaigns).sync_pending() == 1
    blocked = actions.get(task.action_id)
    assert blocked.latest.status == "BLOCKED"
    assert "予測runを確認" in blocked.latest.note

    retried = api.post(
        f"/api/model-drift-review-actions/{task.action_id}/retests",
        json={**_payload(snapshot_id, "phase3q-retest-002"), "expected_revision": 3},
    )
    assert retried.status_code == 202, retried.text
    assert retried.json()["campaign_id"] != started["campaign_id"]
    assert actions.get(task.action_id).latest.status == "IN_PROGRESS"


def test_only_retest_action_and_current_revision_can_start(tmp_path) -> None:
    api, _database, snapshot_id, task, _actions, _retests, _campaigns = _review_fixture(
        tmp_path, action_type="DATA_FIX"
    )
    response = api.post(
        f"/api/model-drift-review-actions/{task.action_id}/retests",
        json=_payload(snapshot_id),
    )
    assert response.status_code == 409
    assert "追加テスト種別" in response.text


def _insert_comparison(database, comparison_id: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO comparison_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                comparison_id,
                1,
                f"phase3q-fingerprint-{comparison_id}",
                "{}",
                "{}",
                "set",
                "official",
                "truth",
                "scope",
                "primary",
                None,
                1,
                1,
                "2026-09-19T00:00:00+00:00",
            ),
        )
