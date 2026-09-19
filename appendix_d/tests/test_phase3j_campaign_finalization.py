"""Phase 3J: 比較キャンペーン自動完了の状態・Worker・API契約。"""

import sqlite3
from types import SimpleNamespace

from test_phase3i_comparison_campaign import _fixture, _request

from forecast_provider.comparison_campaign import (
    CampaignFinalization,
    SqliteComparisonCampaignStore,
)
from forecast_provider.comparison_campaign_worker import work_once


class _Campaigns:
    def __init__(self, finalization):
        self.finalization = finalization
        self.action = None

    def claim_finalization(self):
        value, self.finalization = self.finalization, None
        return value

    def defer_finalization(self, campaign_id):
        self.action = ("defer", campaign_id)

    def complete_finalization(self, campaign_id, comparison_id):
        self.action = ("complete", campaign_id, comparison_id)

    def fail_finalization(self, campaign_id, error_code, error_message):
        self.action = ("fail", campaign_id, error_code, error_message)


class _Evaluation:
    def __init__(self):
        self.request = None

    def create_comparison(self, request):
        self.request = request
        return SimpleNamespace(comparison_id="comparison-001")


def _finalization():
    return CampaignFinalization(
        "campaign-001", "primary", None, "evaluation-v2.9", "RUNNING", "2026-09-17"
    )


def test_worker_defers_until_all_campaign_entries_finish():
    campaigns = _Campaigns(_finalization())
    service = SimpleNamespace(detail=lambda _campaign_id: {"status": "RUNNING"})

    assert work_once(campaigns, service, _Evaluation()) == 1
    assert campaigns.action == ("defer", "campaign-001")


def test_worker_runs_retest_synchronizer_after_campaign_work():
    campaigns = _Campaigns(_finalization())
    service = SimpleNamespace(detail=lambda _campaign_id: {"status": "RUNNING"})
    synchronizer = SimpleNamespace(sync_pending=lambda: setattr(synchronizer, "called", True))
    synchronizer.called = False

    assert work_once(campaigns, service, _Evaluation(), synchronizer) == 1
    assert synchronizer.called is True


def test_worker_builds_fixed_comparison_definition_and_completes():
    campaigns = _Campaigns(_finalization())
    detail = {
        "status": "COMPLETED",
        "snapshot_id": "snapshot-001",
        "requested_by": "analyst",
        "purpose": "OSSモデル選定",
        "entries": [
            {"run_id": "run-b", "conformance_id": "test-b"},
            {"run_id": "run-a", "conformance_id": "test-a"},
        ],
    }
    evaluation = _Evaluation()

    assert work_once(campaigns, SimpleNamespace(detail=lambda _id: detail), evaluation) == 1
    assert campaigns.action == ("complete", "campaign-001", "comparison-001")
    assert evaluation.request == {
        "run_ids": ["run-a", "run-b"],
        "conformance_ids": {"run-b": "test-b", "run-a": "test-a"},
        "truth_snapshot_id": "snapshot-001",
        "mode": "primary",
        "horizon": None,
        "policy_version": "evaluation-v2.9",
        "requested_by": "analyst",
        "purpose": "OSSモデル選定",
    }


def test_worker_persists_safe_failure_for_attention_required_campaign():
    campaigns = _Campaigns(_finalization())
    service = SimpleNamespace(detail=lambda _id: {"status": "NEEDS_ATTENTION"})

    assert work_once(campaigns, service, _Evaluation()) == 1
    assert campaigns.action[:3] == ("fail", "campaign-001", "ValueError")
    assert "失敗" in campaigns.action[3]


def test_api_exposes_definition_status_and_failed_retry(tmp_path):
    api, snapshot_id, _database = _fixture(tmp_path)
    payload = {**_request(snapshot_id), "mode": "horizon", "horizon": 7}

    created = api.post("/api/comparison-campaigns", json=payload)
    assert created.status_code == 202
    campaign_id = created.json()["campaign_id"]
    finalization = created.json()["finalization"]
    assert (finalization["mode"], finalization["horizon"], finalization["status"]) == (
        "horizon",
        7,
        "WAITING",
    )

    campaigns = SqliteComparisonCampaignStore(_database)
    claimed = campaigns.claim_finalization()
    assert claimed is not None and claimed.campaign_id == campaign_id
    assert campaigns.claim_finalization() is None
    campaigns.fail_finalization(campaign_id, "test", "再実行できます")

    failed = api.get(f"/api/comparison-campaigns/{campaign_id}").json()["finalization"]
    assert failed["status"] == "FAILED"
    retried = api.post(f"/api/comparison-campaigns/{campaign_id}/retry-finalization")
    assert retried.status_code == 200
    assert retried.json()["finalization"]["status"] == "WAITING"
    assert campaigns.claim_finalization() is not None
    comparison_id = "comparison-phase3j-test"
    with sqlite3.connect(_database) as connection:
        connection.execute(
            "INSERT INTO comparison_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                comparison_id, 1, "fingerprint-phase3j", "{}", "{}", "set", "official",
                "truth", "scope", "primary", None, 1, 1, "2026-09-17T00:00:00+00:00",
            ),
        )
    campaigns.complete_finalization(campaign_id, comparison_id)
    completed = api.get(f"/api/comparison-campaigns/{campaign_id}").json()["finalization"]
    assert completed["status"] == "SUCCEEDED"
    assert completed["comparison_id"] == comparison_id


def test_campaign_rejects_inconsistent_evaluation_scope(tmp_path):
    api, snapshot_id, _database = _fixture(tmp_path)
    primary = {**_request(snapshot_id), "horizon": 7}
    horizon = {**_request(snapshot_id, "campaign-request-002"), "mode": "horizon"}

    assert api.post("/api/comparison-campaigns", json=primary).status_code == 422
    assert api.post("/api/comparison-campaigns", json=horizon).status_code == 422


def test_schema_backfills_phase3i_campaign_without_finalization(tmp_path):
    api, snapshot_id, database = _fixture(tmp_path)
    created = api.post("/api/comparison-campaigns", json=_request(snapshot_id)).json()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM comparison_campaign_finalizations WHERE campaign_id=?",
            (created["campaign_id"],),
        )

    migrated = SqliteComparisonCampaignStore(database).get_finalization(created["campaign_id"])

    assert migrated is not None
    assert (migrated.mode, migrated.horizon, migrated.status) == ("primary", None, "WAITING")
