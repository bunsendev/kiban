"""Phase 3A: 作成APIの冪等性と統一エラー契約。"""

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_run_api import snapshot_payload

from forecast_provider.api import create_app
from forecast_provider.api.error_responses import install_error_handlers
from forecast_provider.api.http_security import SecuritySettings, install_security_boundary
from forecast_provider.api.idempotency import (
    InMemoryIdempotencyStore,
    PostgresIdempotencyStore,
    SqliteIdempotencyStore,
)
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore


def client(tmp_path, idempotency_path=None):
    database = tmp_path / "api-contract.sqlite3"
    app = create_app(
        SqliteRunStore(database),
        SqliteCatalogStore(database),
        "token",
        idempotency_store=SqliteIdempotencyStore(
            idempotency_path or tmp_path / "idempotency.sqlite3"
        ),
    )
    api = TestClient(app)
    api.headers["Authorization"] = "Bearer token"
    return api


def test_successful_creation_is_replayed_after_app_restart(tmp_path):
    idempotency_path = tmp_path / "idempotency.sqlite3"
    headers = {"Idempotency-Key": "snapshot-create-0001"}
    first_api = client(tmp_path, idempotency_path)
    first = first_api.post("/api/snapshots", json=snapshot_payload(), headers=headers)
    assert first.status_code == 201
    assert first.headers["Idempotency-Replayed"] == "false"

    second_api = client(tmp_path, idempotency_path)
    second = second_api.post("/api/snapshots", json=snapshot_payload(), headers=headers)
    assert second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["Idempotency-Replayed"] == "true"
    assert second.headers["x-request-id"] != first.headers["x-request-id"]


def test_same_key_rejects_changed_request_and_returns_error_contract(tmp_path):
    api = client(tmp_path)
    headers = {"Idempotency-Key": "snapshot-create-0002"}
    assert api.post("/api/snapshots", json=snapshot_payload(), headers=headers).status_code == 201
    changed = snapshot_payload(data=b"changed")
    response = api.post("/api/snapshots", json=changed, headers=headers)

    assert response.status_code == 409
    assert response.json() == {
        "code": "CONFLICT",
        "message": "同じIdempotency-Keyが異なる要求に使われています",
        "details": {},
        "request_id": response.headers["x-request-id"],
    }


def test_failed_creation_releases_key_and_validation_does_not_echo_input(tmp_path):
    api = client(tmp_path)
    headers = {"Idempotency-Key": "snapshot-create-0003"}
    invalid = snapshot_payload()
    invalid["train_start"] = "secret-invalid-value"
    rejected = api.post("/api/snapshots", json=invalid, headers=headers)
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "REQUEST_VALIDATION_FAILED"
    assert "secret-invalid-value" not in rejected.text
    assert rejected.json()["request_id"] == rejected.headers["x-request-id"]

    accepted = api.post("/api/snapshots", json=snapshot_payload(), headers=headers)
    assert accepted.status_code == 201
    assert accepted.headers["Idempotency-Replayed"] == "false"


def test_invalid_key_and_http_errors_share_the_envelope(tmp_path):
    api = client(tmp_path)
    invalid_key = api.post(
        "/api/snapshots",
        json=snapshot_payload(),
        headers={"Idempotency-Key": "contains space"},
    )
    missing = api.get("/api/snapshots/missing")
    unauthorized = TestClient(api.app).get("/api/session")

    assert invalid_key.status_code == 422
    assert invalid_key.json()["code"] == "VALIDATION_ERROR"
    assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
    assert unauthorized.status_code == 401
    assert unauthorized.json()["code"] == "UNAUTHORIZED"
    for response in (invalid_key, missing, unauthorized):
        assert set(response.json()) == {"code", "message", "details", "request_id"}
        assert response.json()["request_id"] == response.headers["x-request-id"]


def test_pending_claim_blocks_duplicates_and_expired_lease_can_be_reclaimed():
    store = InMemoryIdempotencyStore()
    now = datetime.now(UTC)
    assert store.claim("scope", "request", now)[0] == "CLAIMED"
    assert store.claim("scope", "request", now)[0] == "IN_PROGRESS"
    assert store.claim("scope", "changed", now)[0] == "MISMATCH"
    assert store.claim("scope", "changed", now + timedelta(minutes=16))[0] == "CLAIMED"


def test_unexpected_exception_is_sanitized():
    app = FastAPI()
    install_error_handlers(app)
    install_security_boundary(app, SecuritySettings())

    @app.get("/api/failure")
    def failure():
        raise RuntimeError("secret database location")

    response = TestClient(app, raise_server_exceptions=False).get("/api/failure")
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "secret database location" not in response.text
    assert response.json()["request_id"] == response.headers["x-request-id"]


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_idempotency_store_roundtrip():
    store = PostgresIdempotencyStore(os.environ["KIBAN_TEST_POSTGRES_DSN"])
    # HTTP統合試験と異なる固定scopeにし、再実行可能な内容へ収束させる。
    now = datetime.now(UTC)
    scope = f"phase3a-{now.timestamp()}"
    outcome, _ = store.claim(scope, "request", now)
    assert outcome == "CLAIMED"
    store.complete(scope, "request", 201, "application/json", b'{"id":"x"}', now)
    outcome, record = store.claim(scope, "request", now)
    assert outcome == "REPLAY"
    assert record.response_body == b'{"id":"x"}'
