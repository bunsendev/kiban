"""共有PHP契約と終業時再送を人工Packageで検証する。"""

import hashlib
import json
import sqlite3
import urllib.error
from datetime import UTC, datetime, timedelta

import pytest

from forecast_provider.feedback_sync import transport as module
from forecast_provider.feedback_sync.client import connection_test
from forecast_provider.feedback_sync.policy import DEFAULT_FLAGS, FeedbackStore
from forecast_provider.feedback_sync.privacy import manifest, minimize, validate_package
from forecast_provider.feedback_sync.signals import collect_context
from forecast_provider.feedback_sync.transport import (
    SharedServerTransport,
    classify_connection_error,
    send_pending,
)


def _item():
    body = b'{"encrypted":"fixture"}'
    return {"package_id": "a" * 32, "envelope": body,
            "sha256": hashlib.sha256(body).hexdigest(),
            "policy_version": "feedback-test-v1"}


def test_shared_transport_headers_and_strict_ack(monkeypatch):
    item = _item()
    seen = {}

    def fake_post(request, timeout):
        seen["request"] = request
        seen["timeout"] = timeout
        return {"ok": True, "status": "RECEIVED", "request_id": item["package_id"],
                "sha256": item["sha256"]}

    monkeypatch.setattr(module, "_post", fake_post)
    transport = SharedServerTransport("https://bun.stock-tools.tech/upload.php",
                                      "BUNSEN-PILOT-01")
    assert transport.send(item, "t" * 40) == {"status": "ACCEPTED",
                                               "package_id": item["package_id"]}
    headers = dict(seen["request"].header_items())
    assert seen["request"].get_method() == "POST"
    assert headers["Content-type"] == "application/octet-stream"
    assert headers["X-bunsen-client"] == "BUNSEN-PILOT-01"
    assert headers["X-bunsen-request-id"] == item["package_id"]
    assert headers["X-bunsen-sha256"] == item["sha256"]
    assert headers["X-bunsen-privacy"] == item["policy_version"]
    assert seen["request"].data == item["envelope"]


@pytest.mark.parametrize("response", [
    {"ok": True, "status": "RECEIVED"},
    {"ok": True, "status": "RECEIVED", "request_id": "b" * 32},
    {"ok": True, "status": "RECEIVED", "request_id": "a" * 32,
     "sha256": "0" * 64},
    {"ok": False, "status": "RECEIVED", "request_id": "a" * 32},
])
def test_shared_transport_does_not_mark_ambiguous_ack(monkeypatch, response):
    monkeypatch.setattr(module, "_post", lambda *_: response)
    with pytest.raises(ValueError, match="FEEDBACK_ACK"):
        SharedServerTransport("https://server.example/upload.php", "client-a").send(
            _item(), "t" * 40,
        )


def test_shared_transport_duplicate(monkeypatch):
    monkeypatch.setattr(module, "_post", lambda *_: {
        "ok": True, "status": "DUPLICATE", "request_id": "a" * 32,
    })
    assert SharedServerTransport("https://server.example/upload.php", "client-a").send(
        _item(), "t" * 40,
    )["status"] == "DUPLICATE"


def test_outbox_backoff_restart_and_non_retryable_rejection(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    item = _item()
    store.queue(item["package_id"], item["policy_version"], item["envelope"],
                destination_url="https://server.example/upload.php",
                transport_kind="shared_php")

    class Offline:
        kind = "shared_php"

        def send(self, _item, _token):
            raise urllib.error.URLError("offline")

    first = send_pending(store, url="https://server.example/upload.php", token="t" * 40,
                         transport=Offline())
    assert first["retryable"] == 1 and first["deferred"] == 1
    restarted = FeedbackStore(store.path)
    second = send_pending(restarted, url="https://server.example/upload.php",
                          token="t" * 40, transport=Offline())
    assert second["retryable"] == 0 and second["deferred"] == 1
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE outbox SET next_attempt_at=?", (
            (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        ))

    class Success:
        kind = "shared_php"

        def send(self, item, _token):
            return {"status": "DUPLICATE", "package_id": item["package_id"]}

    third = send_pending(restarted, url="https://server.example/upload.php",
                         token="t" * 40, transport=Success())
    assert third["sent"] == 1 and third["deferred"] == 0
    assert restarted.status()["last_sync"]

    other = {**item, "package_id": "b" * 32}
    restarted.queue(other["package_id"], other["policy_version"], other["envelope"],
                    destination_url="https://server.example/upload.php",
                    transport_kind="shared_php")

    class Rejected:
        kind = "shared_php"

        def send(self, _item, _token):
            raise urllib.error.HTTPError("https://server.example", 403, "denied", {}, None)

    assert send_pending(restarted, url="https://server.example/upload.php",
                        token="t" * 40, transport=Rejected())["rejected"] == 1
    assert restarted.status()["rejected_package"] == 1
    assert restarted.pending() == []


def test_connection_test_contains_no_business_values(monkeypatch):
    class Capturing:
        def send(self, item, _token):
            envelope = json.loads(item["envelope"])
            assert envelope["package_id"] == item["package_id"]
            assert item["policy_version"] == "CONNECTION_TEST"
            assert b"4901234567890" not in item["envelope"]
            return {"status": "ACCEPTED", "package_id": item["package_id"]}

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
    client = {"transport": "shared_php", "client_id": "client-a",
              "endpoint": "https://server.example/upload.php"}
    assert connection_test(client, "t" * 40, public, transport=Capturing()) == {
        "status": "CONNECTED",
    }


@pytest.mark.parametrize(("code", "expected"), [
    (403, "rejected"), (401, "rejected"), (413, "rejected"),
    (500, "retryable"), (429, "retryable"),
])
def test_http_rejection_and_retry_policy(tmp_path, code, expected):
    item = _item()
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    store.queue(item["package_id"], item["policy_version"], item["envelope"],
                destination_url="https://server.example/upload.php",
                transport_kind="shared_php")

    class Failing:
        kind = "shared_php"

        def send(self, _item, _token):
            raise urllib.error.HTTPError("https://server.example", code, "error", {}, None)

    result = send_pending(store, url="https://server.example/upload.php",
                          token="t" * 40, transport=Failing())
    assert result[expected] == 1
    assert store.status()["rejected_package"] == (1 if expected == "rejected" else 0)


@pytest.mark.parametrize(("code", "status"), [
    (401, "AUTH"), (403, "PRIVACY_POLICY"), (404, "CLIENT_ID"), (500, "SERVER"),
])
def test_connection_error_is_classified_without_response_body(code, status):
    error = urllib.error.HTTPError("https://server.example", code, "error", {}, None)
    assert classify_connection_error(error) == status


def test_reconfigured_destination_never_receives_old_outbox(tmp_path):
    item = _item()
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    store.queue(item["package_id"], item["policy_version"], item["envelope"],
                destination_url="https://old.example/upload.php", transport_kind="shared_php")

    class MustNotSend:
        kind = "shared_php"

        def send(self, _item, _token):
            raise AssertionError("old package was sent to a new destination")

    result = send_pending(store, url="https://new.example/upload.php",
                          token="t" * 40, transport=MustNotSend())
    assert result["rejected"] == 1 and store.status()["rejected_package"] == 1


def test_aggregate_learning_changes_and_freshness_without_identifiers(tmp_path):
    inbox = tmp_path / "Inbox"
    settings = tmp_path / "Settings"
    inbox.mkdir()
    settings.mkdir()
    day = (datetime.now(UTC) + timedelta(hours=9)).date()
    recorded = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(inbox / "inbox.sqlite3") as db:
        db.execute("CREATE TABLE learning_events(action TEXT, actor TEXT, recorded_at TEXT)")
        db.execute("INSERT INTO learning_events VALUES (?,?,?)",
                   ("OPERATOR_CONFIRM", "PRIVATE_OPERATOR", recorded))
    with sqlite3.connect(settings / "field-settings.sqlite3") as db:
        db.execute("CREATE TABLE setting_changes(change_type TEXT,target TEXT,changed_at TEXT)")
        db.execute("INSERT INTO setting_changes VALUES (?,?,?)",
                   ("JAN_MAPPING", "PRIVATE_JAN", recorded))
    context = collect_context(inbox, settings, day)
    flags = DEFAULT_FLAGS.copy()
    flags.update(diagnostics=True, learning_summary=True, change_summary=True,
                 data_freshness=True)
    payload = minimize([{"event_type": "FORECAST_READY", "outcome": "OK",
                         "error_code": None, "metrics_json": "{}"}],
                       {"level": 2, "flags": flags}, client_id="client-a",
                       context=context)
    package = {"level": 2, "payload": payload,
               "manifest": manifest(payload, policy_version="v1", application_version="2.9.0")}
    validate_package(package, max_level=2)
    assert payload["data_freshness"] == "FRESH"
    assert payload["learning_summary"] == [{"kind": "OPERATOR_CONFIRM", "count": 1}]
    assert payload["change_summary"] == [{"kind": "JAN_MAPPING", "count": 1}]
    assert "PRIVATE_OPERATOR" not in json.dumps(payload)
    assert "PRIVATE_JAN" not in json.dumps(payload)


def test_existing_outbox_migrates_without_losing_encrypted_body(tmp_path):
    path = tmp_path / "feedback.sqlite3"
    body = _item()["envelope"]
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE outbox (package_id TEXT PRIMARY KEY,created_at TEXT,"
                   "policy_version TEXT,envelope BLOB,sha256 TEXT,state TEXT,"
                   "attempts INTEGER,last_error TEXT,sent_at TEXT)")
        db.execute("INSERT INTO outbox VALUES (?,?,?,?,?,'PENDING',0,NULL,NULL)", (
            "a" * 32, datetime.now(UTC).isoformat(), "v1", body,
            hashlib.sha256(body).hexdigest(),
        ))
    store = FeedbackStore(path)
    pending = store.pending()
    assert len(pending) == 1 and pending[0]["envelope"] == body
    assert pending[0]["next_attempt_at"] is None
    assert pending[0]["destination_url"] is None
