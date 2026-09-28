"""送信Policy、最小化、暗号化、受信側拒否、再送を人工データで確認。"""

import base64
import hashlib
import json
import sqlite3
import urllib.error
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.feedback_sync.client import finish_day
from forecast_provider.feedback_sync.crypto import decrypt_package, encrypt_package
from forecast_provider.feedback_sync.policy import DEFAULT_FLAGS, FeedbackStore
from forecast_provider.feedback_sync.privacy import manifest, minimize, pseudonym
from forecast_provider.feedback_sync.server import FeedbackServerStore, create_server
from forecast_provider.feedback_sync.support import queue_support
from forecast_provider.feedback_sync.updates import check_update
from forecast_provider.field_pilot.improvement_events import ImprovementEventLedger
from forecast_provider.field_pilot.read_model import FieldPilotReadService
from forecast_provider.jobs import SqliteRunStore


@pytest.fixture
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    return (
        private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()),
        private.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo),
    )


def _policy(level=2, **enabled):
    flags = DEFAULT_FLAGS.copy()
    flags.update(enabled)
    return {"level": level, "flags": flags}


def test_default_off_and_versioned_policy(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    assert store.current()["policy"]["level"] == 0
    with pytest.raises(ValueError, match="LEVEL_CONFLICT"):
        store.change(_policy(1, absolute_quantities=True), expected_version=None,
                     actor="admin", reason="test")
    first = store.change(_policy(2, diagnostics=True), expected_version=None,
                         actor="admin", reason="approved")
    with pytest.raises(ValueError, match="VERSION_CONFLICT"):
        store.change(_policy(1, diagnostics=True), expected_version=None,
                     actor="admin", reason="stale")
    second = store.change(_policy(1, diagnostics=True), expected_version=first["version"],
                          actor="admin", reason="reduce")
    assert second["previous_version"] == first["version"]


def test_minimization_pseudonyms_and_manifest_do_not_expose_raw_values():
    rows = [{"event_type": "FORECAST_READY", "outcome": "OK", "error_code": None,
             "metrics_json": '{"duration_ms":12,"item_count":31}',
             "jan": "4901234567890", "location_id": "SECRET-WAREHOUSE"}]
    secret = b"x" * 32
    assert pseudonym(secret, "client-a", "PRODUCT", rows[0]["jan"]) == pseudonym(
        secret, "client-a", "PRODUCT", rows[0]["jan"],
    )
    assert pseudonym(secret, "client-a", "PRODUCT", rows[0]["jan"]) != pseudonym(
        secret, "client-b", "PRODUCT", rows[0]["jan"],
    )
    aggregate = minimize(rows, _policy(2, diagnostics=True, forecast_metrics=True),
                         client_id="client-a", secret=secret)
    assert aggregate["details"] == []
    assert "4901234567890" not in json.dumps(aggregate)
    assert "SECRET-WAREHOUSE" not in json.dumps(aggregate)
    detail = minimize(rows, _policy(3, diagnostics=True, pseudonymous_products=True,
                                    pseudonymous_warehouses=True, absolute_quantities=True),
                      client_id="client-a", secret=secret)
    assert detail["details"][0]["product_id"].startswith("PRODUCT_")
    assert detail["details"][0]["metrics"]["item_count"] == 31
    assert "4901234567890" not in json.dumps(detail)
    assert manifest(detail, policy_version="v1", application_version="2.9.0")[
        "contains_absolute_inventory"
    ] is True


def test_envelope_rejects_tampering_and_server_enforces_policy(tmp_path, keys):
    private, public = keys
    client_policy = _policy(2, diagnostics=True)
    payload = minimize([{"event_type": "VIEW_READY", "outcome": "OK", "error_code": None,
                         "metrics_json": "{}", "jan": "4901234567890", "location_id": "W1"}],
                       client_policy, client_id="site-a", secret=b"k" * 32)
    package = {"level": 2, "payload": payload,
               "manifest": manifest(payload, policy_version="policy-v1",
                                    application_version="2.9.0")}
    package_id = uuid.uuid4().hex
    envelope = encrypt_package(package, public, package_id=package_id, client_id="site-a")
    assert decrypt_package(envelope, private)[1] == package
    tampered = json.loads(envelope)
    tampered["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        decrypt_package(json.dumps(tampered).encode(), private)
    changed = json.loads(envelope)
    cipher = bytearray(base64.b64decode(changed["ciphertext"]))
    cipher[-1] ^= 1
    changed["ciphertext"] = base64.b64encode(cipher).decode()
    changed["sha256"] = hashlib.sha256(cipher).hexdigest()
    with pytest.raises(InvalidTag):
        decrypt_package(json.dumps(changed).encode(), private)
    store = FeedbackServerStore(tmp_path / "server.sqlite3")
    store.enroll("site-a", "t" * 40, "policy-v1", client_policy)
    app = create_server(store, private)
    with TestClient(app, base_url="http://feedback.example") as insecure:
        assert insecure.post("/v1/feedback", content=envelope).status_code == 403
    with TestClient(app, base_url="https://feedback.example") as http:
        headers = {"Authorization": "Bearer " + "t" * 40}
        assert http.post("/v1/feedback", content=envelope).status_code == 401
        accepted = http.post("/v1/feedback", content=envelope, headers=headers)
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "ACCEPTED"
        assert http.post("/v1/feedback", content=envelope, headers=headers).json()[
            "status"
        ] == "DUPLICATE"
        changed = encrypt_package({**package, "level": 3}, public,
                                  package_id=uuid.uuid4().hex, client_id="site-a")
        assert http.post("/v1/feedback", content=changed, headers=headers).status_code == 422
        assert http.post("/v1/feedback", content=envelope, headers=headers,
                         ).status_code == 200
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM received").fetchone()[0] == 1


def test_server_rejects_raw_fields_even_when_encrypted(tmp_path, keys):
    private, public = keys
    approved = _policy(3, diagnostics=True, pseudonymous_products=True)
    store = FeedbackServerStore(tmp_path / "server.sqlite3")
    store.enroll("site-a", "t" * 40, "v1", approved)
    payload = {"event_counts": [], "metric_summary": [], "details": [{
        "event_type": "VIEW_READY", "outcome": "OK", "error_code": None,
        "product_id": "PRODUCT_4901234567890", "metrics": {},
    }]}
    package = {"level": 3, "payload": payload,
               "manifest": manifest(payload, policy_version="v1", application_version="2.9.0")}
    envelope = encrypt_package(package, public, package_id=uuid.uuid4().hex,
                               client_id="site-a")
    with TestClient(create_server(store, private), base_url="https://feedback.example") as http:
        response = http.post("/v1/feedback", content=envelope,
                             headers={"Authorization": "Bearer " + "t" * 40})
    assert response.status_code == 422


def test_server_rejects_details_when_diagnostics_not_approved(tmp_path, keys):
    private, public = keys
    approved = _policy(3)
    store = FeedbackServerStore(tmp_path / "server.sqlite3")
    store.enroll("site-a", "t" * 40, "v1", approved)
    payload = {"event_counts": [], "metric_summary": [], "details": [{
        "event_type": "VIEW_READY", "outcome": "OK", "error_code": None,
        "metrics": {},
    }]}
    package = {"level": 3, "payload": payload,
               "manifest": manifest(payload, policy_version="v1", application_version="2.9.0")}
    envelope = encrypt_package(package, public, package_id=uuid.uuid4().hex,
                               client_id="site-a")
    with TestClient(create_server(store, private), base_url="https://feedback.example") as http:
        response = http.post("/v1/feedback", content=envelope,
                             headers={"Authorization": "Bearer " + "t" * 40})
    assert response.status_code == 422


def test_server_retention_uses_category_policies(tmp_path):
    store = FeedbackServerStore(tmp_path / "server.sqlite3")
    old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    with sqlite3.connect(store.path) as db:
        for index, category in enumerate(("DIAGNOSTIC", "IMPROVEMENT", "SUPPORT")):
            db.execute("INSERT INTO received VALUES (?,?,?,?,?,?,?)", (
                f"id-{index}", "site-a", old, "{}", "v1", category, "hash",
            ))
    assert store.prune({"DIAGNOSTIC": 30, "IMPROVEMENT": 90, "SUPPORT": 7}) == 2
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT category FROM received").fetchone()[0] == "IMPROVEMENT"


def test_outbox_retries_and_duplicate_ack(tmp_path, keys):
    _, public = keys
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    policy = store.change(_policy(1, diagnostics=True), expected_version=None,
                          actor="admin", reason="test")
    client = {"client_id": "site-a", "endpoint": "https://feedback.example/v1/feedback"}
    attempt = {"n": 0}

    def sender(_url, _token, envelope):
        attempt["n"] += 1
        if attempt["n"] == 1:
            raise urllib.error.URLError("offline")
        return {"status": "DUPLICATE", "package_id": json.loads(envelope)["package_id"]}

    first = finish_day(store, improvement_db=tmp_path / "missing.sqlite3", client=client,
                       hmac_secret=b"x" * 32, token="t" * 40, public_key=public,
                       sender=sender)
    assert first["status"] == "SAVED_FOR_RETRY"
    assert len(store.pending()) == 1
    assert store.pending(force=False) == []
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE outbox SET next_attempt_at=?", (
            (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        ))
    second = finish_day(store, improvement_db=tmp_path / "missing.sqlite3", client=client,
                        hmac_secret=b"x" * 32, token="t" * 40, public_key=public,
                        sender=sender)
    assert second["status"] == "COMPLETED"
    assert second["sent"] == 1
    assert store.pending() == []
    assert policy["version"]


def test_admin_ui_requires_token_and_uses_versioned_settings(tmp_path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    service = FieldPilotReadService(None, tmp_path / "Config" / "pilot-settings.json",
                                    inbox_root=inbox, learning_admin_token="admin-secret")
    app = create_app(SqliteRunStore(tmp_path / "app.sqlite3"),
                     SqliteCatalogStore(tmp_path / "app.sqlite3"), "api-secret",
                     field_pilot=service)
    with TestClient(app, base_url="http://127.0.0.1") as http:
        assert http.get("/ui/pilot/feedback").status_code == 200
        assert "Feedback Server 接続テスト" in http.get(
            "/ui/pilot/feedback",
        ).text
        assert "本日の作業を完了" in http.get("/ui/pilot").text
        assert http.get("/api/field-pilot/feedback").status_code == 403
        headers = {"X-Field-Pilot-Admin-Token": "admin-secret"}
        current = http.get("/api/field-pilot/feedback", headers=headers).json()
        assert current["policy"]["level"] == 0
        assert current["sync"]["pending_outbox"] == 0
        assert current["connection"] is None
        change = {"policy": _policy(2, diagnostics=True), "expected_version": None,
                  "actor": "admin", "reason": "client approval"}
        assert http.post("/api/field-pilot/feedback/change", json=change).status_code == 403
        saved = http.post("/api/field-pilot/feedback/change", json=change, headers=headers)
        assert saved.status_code == 200
        assert saved.json()["version"]
        assert http.post("/api/field-pilot/feedback/change", json=change,
                         headers=headers).status_code == 409


def test_support_consent_is_time_limited_and_single_use(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    with pytest.raises(ValueError, match="CONSENT_INVALID"):
        store.consent(target="report.csv", purpose="support", destination="central",
                      actor="admin", expires_at=datetime.now(UTC) - timedelta(seconds=1))
    consent_id = store.consent(target="report.csv", purpose="support",
                               destination="central", actor="admin",
                               expires_at=datetime.now(UTC) + timedelta(minutes=10))
    assert not store.use_consent(consent_id, target="other.csv", destination="central")
    assert store.use_consent(consent_id, target="report.csv", destination="central")
    assert not store.use_consent(consent_id, target="report.csv", destination="central")


def test_support_file_requires_local_consent_and_central_grant(tmp_path, keys):
    private, public = keys
    local = FeedbackStore(tmp_path / "local.sqlite3")
    central = FeedbackServerStore(tmp_path / "central.sqlite3")
    central.enroll("site-a", "t" * 40, "off-v1", _policy(0))
    source = tmp_path / "report.csv"
    source.write_bytes(b"secret,quantity\nitem,25\n")
    consent_id = local.consent(target=source.name, purpose="single support issue",
                               destination="https://feedback.example/v1/feedback",
                               actor="admin", expires_at=datetime.now(UTC) + timedelta(hours=1))
    package_id = queue_support(
        local, consent_id=consent_id, source=source, client_id="site-a",
        destination="https://feedback.example/v1/feedback", public_key=public,
    )
    with pytest.raises(ValueError, match="CONSENT_MISSING_OR_EXPIRED"):
        queue_support(local, consent_id=consent_id, source=source, client_id="site-a",
                      destination="https://feedback.example/v1/feedback", public_key=public)
    envelope = local.pending()[0]["envelope"]
    headers = {"Authorization": "Bearer " + "t" * 40}
    with TestClient(create_server(central, private), base_url="https://feedback.example") as http:
        assert http.post("/v1/feedback", content=envelope, headers=headers).status_code == 422
        central.grant_support(client_id="site-a", consent_id=consent_id,
                              file_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                              expires_at=datetime.now(UTC) + timedelta(minutes=30),
                              max_bytes=source.stat().st_size)
        assert http.post("/v1/feedback", content=envelope, headers=headers).json() == {
            "status": "ACCEPTED", "package_id": package_id,
        }
        assert http.post("/v1/feedback", content=envelope, headers=headers).json()[
            "status"
        ] == "DUPLICATE"
    with sqlite3.connect(central.path) as db:
        stored = db.execute("SELECT payload_json,category FROM received").fetchone()
    assert stored[1] == "SUPPORT"
    assert "secret,quantity" not in stored[0]


def test_update_manifest_requires_signature_and_https():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    manifest = {"version": "2.10.0", "sha256": "a" * 64,
                "artifact_url": "https://updates.example/release.zip"}
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    document = {"manifest": manifest,
                "signature": base64.b64encode(key.sign(canonical)).decode()}
    raw = json.dumps(document).encode()
    assert check_update("https://updates.example/manifest", public, "2.9.0",
                        fetcher=lambda _: raw)["available"] is True
    assert check_update("https://updates.example/manifest", public, "2.10.0",
                        fetcher=lambda _: raw)["available"] is False
    with pytest.raises(ValueError, match="UPDATE_TLS_REQUIRED"):
        check_update("http://updates.example/manifest", public, "2.9.0",
                     fetcher=lambda _: raw)
    document["manifest"]["version"] = "2.11.0"
    with pytest.raises(InvalidSignature):
        check_update("https://updates.example/manifest", public, "2.9.0",
                     fetcher=lambda _: json.dumps(document).encode())
    def offline(_):
        raise urllib.error.URLError("offline")

    with pytest.raises(urllib.error.URLError):
        check_update("https://updates.example/manifest", public, "2.9.0",
                     fetcher=offline)


def test_synthetic_improvement_ledger_to_central_receiver(tmp_path, keys):
    private, public = keys
    day = datetime.now(UTC).date()
    ledger = ImprovementEventLedger(tmp_path / "improvement-events.sqlite3")
    ledger.append("FORECAST_READY", outcome="OK", business_date=day,
                  jan="4901234567890", location_id="WAREHOUSE_SECRET",
                  metrics={"duration_ms": 120, "item_count": 10})
    local = FeedbackStore(tmp_path / "feedback.sqlite3")
    current = local.change(_policy(2, diagnostics=True, forecast_metrics=True),
                           expected_version=None, actor="admin", reason="synthetic test")
    central = FeedbackServerStore(tmp_path / "central.sqlite3")
    central.enroll("site-a", "t" * 40, current["version"], current["policy"])
    with TestClient(create_server(central, private), base_url="https://feedback.example") as http:
        def sender(_url, token, envelope):
            response = http.post("/v1/feedback", content=envelope,
                                 headers={"Authorization": "Bearer " + token})
            response.raise_for_status()
            return response.json()

        result = finish_day(
            local, improvement_db=ledger.path,
            client={"client_id": "site-a", "endpoint": "https://feedback.example/v1/feedback"},
            hmac_secret=b"k" * 32, token="t" * 40, public_key=public,
            day=day, sender=sender,
        )
    assert result["status"] == "COMPLETED"
    with sqlite3.connect(central.path) as db:
        payload = db.execute("SELECT payload_json FROM received").fetchone()[0]
    assert '"count":1' in payload and '"duration_ms"' in payload
    assert "4901234567890" not in payload and "WAREHOUSE_SECRET" not in payload
    assert "item_count" not in payload
