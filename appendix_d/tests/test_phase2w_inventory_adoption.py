"""Phase 2W: 在庫正規化結果の承認・採用版管理。"""

from collections import Counter

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.inventory_normalization import SqliteInventoryNormalizationStore
from forecast_provider.jobs import SqliteRunStore


def _complete(store, *, quarantined=0):
    job_id = store.enqueue("client-uploads/batch", "product-jan-" + "c" * 64, "バラ", "担当")
    store.claim()
    store.progress(job_id, 1, 1, 1, quarantined, Counter({"QUANTITY_INVALID": quarantined}))
    store.complete(
        job_id,
        [("2026-09-01", "4901234567894", "C01", "バラ", "5")],
        "5.0",
        "5.00",
    )
    return job_id


def test_approved_inventory_becomes_current_immutable_adoption(tmp_path):
    database = tmp_path / "adoption.sqlite3"
    store = SqliteInventoryNormalizationStore(database)
    job_id = _complete(store)
    client = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            inventory_normalization=store,
        )
    )
    client.headers["Authorization"] = "Bearer token"

    response = client.post(
        f"/api/inventory-normalization-jobs/{job_id}/decisions",
        json={
            "decision_version": "inventory-adoption-v1",
            "decision": "APPROVED",
            "decided_by": "spoofed-user",
            "reason": "数量一致と隔離0行を確認",
        },
    )
    assert response.status_code == 201
    decisions = client.get(
        f"/api/inventory-normalization-jobs/{job_id}/decisions"
    ).json()
    assert len(decisions) == 1
    assert decisions[0]["decided_by"] == "local-admin"
    assert decisions[0]["decision"] == "APPROVED"
    current = client.get("/api/inventory-normalization-adoption").json()["current"]
    assert current["job_id"] == job_id
    assert current["decision_version"] == "inventory-adoption-v1"

    duplicate = client.post(
        f"/api/inventory-normalization-jobs/{job_id}/decisions",
        json={
            "decision_version": "inventory-adoption-v1",
            "decision": "APPROVED",
            "reason": "再利用",
        },
    )
    assert duplicate.status_code == 422


def test_quarantined_inventory_can_be_rejected_but_not_approved(tmp_path):
    database = tmp_path / "rejected.sqlite3"
    store = SqliteInventoryNormalizationStore(database)
    job_id = _complete(store, quarantined=1)

    try:
        store.decide(job_id, "blocked-v1", "APPROVED", "approver", "隔離あり")
    except ValueError as exc:
        assert "隔離0行" in str(exc)
    else:
        raise AssertionError("隔離行を含むjobを採用できてしまいました")

    decision_id = store.decide(job_id, "rejected-v1", "REJECTED", "approver", "要修正")
    assert decision_id
    assert store.current_adoption() is None
    assert store.list_decisions(job_id)[0]["decision"] == "REJECTED"


def test_inventory_decision_requires_authentication(tmp_path):
    database = tmp_path / "auth.sqlite3"
    store = SqliteInventoryNormalizationStore(database)
    job_id = _complete(store)
    client = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            inventory_normalization=store,
        )
    )
    response = client.post(
        f"/api/inventory-normalization-jobs/{job_id}/decisions",
        json={
            "decision_version": "unauthorized-v1",
            "decision": "APPROVED",
            "reason": "unauthorized",
        },
    )
    assert response.status_code == 401
