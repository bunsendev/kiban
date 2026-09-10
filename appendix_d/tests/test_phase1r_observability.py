"""Phase 1Rの監査log、readiness、運用指標。"""

import json
import logging

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.api.authentication import TokenAuthenticator
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore

TOKEN = "analyst-token-0000000000000000000"


def make_api(tmp_path, readiness_checks=None) -> TestClient:
    database = tmp_path / "observability.sqlite3"
    authenticator = TokenAuthenticator.from_json(
        json.dumps(
            [{"token": TOKEN, "subject": "operator@example.test", "roles": ["ANALYST"]}]
        )
    )
    return TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            authenticator,
            readiness_checks=readiness_checks,
        )
    )


def test_liveness_readiness_metrics_and_structured_audit_log(tmp_path, caplog):
    api = make_api(tmp_path, {"dependency": lambda: True})
    headers = {"Authorization": f"Bearer {TOKEN}"}
    audit_logger = logging.getLogger("kiban.audit")
    assert audit_logger.isEnabledFor(logging.INFO)
    audit_logger.addHandler(caplog.handler)

    try:
        assert api.get("/health?secret=do-not-log").json() == {"status": "ok"}
        assert api.get("/ready").json() == {
            "status": "ready",
            "checks": {"dependency": True, "authentication": True},
        }
        response = api.post(
            "/api/runs", json={"experiment_id": "missing"}, headers=headers
        )
        assert response.status_code == 404
        metrics = api.get("/metrics", headers=headers)
        assert metrics.status_code == 200
        assert "kiban_http_requests_total" in metrics.text
        assert 'route="/api/runs"' in metrics.text
        assert api.get("/metrics").status_code == 401
    finally:
        audit_logger.removeHandler(caplog.handler)

    records = [json.loads(record.message) for record in caplog.records]
    audit = next(record for record in records if record["route"] == "/api/runs")
    assert audit["audit"] is True
    assert audit["subject"] == "operator@example.test"
    assert audit["roles"] == ["ANALYST"]
    assert audit["request_id"] == response.headers["x-request-id"]
    serialized = "\n".join(record.message for record in caplog.records)
    assert TOKEN not in serialized
    assert "do-not-log" not in serialized
    assert "missing" not in serialized


def test_readiness_failure_returns_503_without_details(tmp_path):
    api = make_api(tmp_path, {"database": lambda: False})
    response = api.get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": False, "authentication": True},
    }
