import hashlib
import io
import json
import time
import urllib.error

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from forecast_provider.feedback_sync.crypto import decrypt_package
from portable.api.app import create_app
from portable.api.business_archive import atomic_json
from portable.api.field_store import FieldStore
from portable.runtime.feedback_admin import authorized, issue
from portable.runtime.feedback_delivery import FeedbackDelivery, receiver_identity
from portable.runtime.paths import DataPaths


def pem(key):
    return (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "credentials"))
    paths = DataPaths(tmp_path / "Data")
    paths.ensure()
    delivery = FeedbackDelivery(paths)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    config = {
        "enabled": True,
        "consent": True,
        "client_id": "BUNSEN-PILOT-TEST",
        "token": "synthetic-token-" + "A" * 40,
        "endpoint": "https://example.test/upload.php",
        "public_key": pem(key),
        "key_id": "BUNSEN-KEY-001",
    }
    delivery.configure(config)
    FieldStore(paths.state / "field-ui.sqlite3").feedback({"step": 1, "comment": "test"})
    return delivery, config, key


def test_key_rotation_retains_ciphertext_and_key_metadata(setup):
    delivery, config, old_key = setup
    delivery.collect()
    old = delivery.store.pending(force=True)[0]
    new = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    changed = {**config, "public_key": pem(new), "key_id": "BUNSEN-KEY-002"}
    with pytest.raises(ValueError, match="APPROVAL"):
        delivery.configure(changed)
    delivery.configure({**changed, "confirm_key_change": True})
    pending = delivery.store.pending(force=True)[0]
    assert pending["envelope"] == old["envelope"]
    assert pending["package_id"] == old["package_id"]
    env, package = decrypt_package(
        pending["envelope"],
        old_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    assert env["key_id"] == "BUNSEN-KEY-001"
    assert env["key_fingerprint"] == receiver_identity(pem(old_key))
    assert package["receiver_key"]["key_id"] == env["key_id"]
    assert delivery.config()["key_fingerprint"] == receiver_identity(pem(new))


def test_token_rotation_requeues_auth_and_never_logs_token(setup):
    delivery, config, _ = setup
    delivery.collect()
    item = delivery.store.pending(force=True)[0]
    delivery.store.mark(item["package_id"], "REJECTED", "AUTH_FAILED")
    replacement = "synthetic-new-token-" + "B" * 40
    delivery.configure({**config, "token": replacement})
    assert delivery.store.pending(force=True)[0]["package_id"] == item["package_id"]
    restarted = FeedbackDelivery(delivery.paths)
    assert restarted.token.load() == replacement
    with delivery.store._db() as db:
        ledger = json.dumps([tuple(r) for r in db.execute("SELECT * FROM change_ledger")])
    for secret in (config["token"], replacement):
        assert secret not in ledger
        assert secret not in json.dumps(delivery.status())
        assert secret not in delivery.config_path.read_text("utf-8")


@pytest.mark.parametrize(
    "code,classification",
    [
        ("AUTH_FAILED", "AUTH"),
        ("CLIENT_NOT_ALLOWED", "CLIENT_ID"),
        ("KEY_INVALID", "KEY"),
        ("PRIVACY_REJECTED", "PRIVACY_POLICY"),
    ],
)
def test_receiver_failure_classification_and_no_infinite_retry(
    setup, monkeypatch, code, classification
):
    delivery, _, _ = setup

    def reject(*args):
        raise urllib.error.HTTPError(
            "https://example.test",
            403,
            "denied",
            {},
            io.BytesIO(json.dumps({"error": code}).encode()),
        )

    monkeypatch.setattr("forecast_provider.feedback_sync.transport._post", reject)
    assert delivery.connection_test()["status"] == classification
    delivery.send(manual=True)
    assert delivery.status()["rejected_package"] == 1
    assert not delivery.store.pending(force=True)


def test_already_received_is_success_and_metadata_tamper_rejected(setup, monkeypatch):
    delivery, _, key = setup
    captured = []

    def receive(request, timeout):
        envelope = json.loads(request.data)
        captured.append(envelope)
        return {
            "ok": True,
            "status": "ALREADY_RECEIVED",
            "request_id": envelope["package_id"],
            "sha256": hashlib.sha256(request.data).hexdigest(),
        }

    monkeypatch.setattr("forecast_provider.feedback_sync.transport._post", receive)
    assert delivery.connection_test()["status"] == "CONNECTED"
    assert captured[0]["key_id"] == "BUNSEN-KEY-001"
    captured[0]["key_id"] = "tampered"
    with pytest.raises(ValueError, match="METADATA"):
        decrypt_package(
            json.dumps(captured[0]).encode(),
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )


def test_admin_gate_expiry_public_view_and_finish_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTABLE_SMOKE", "1")
    app = create_app(tmp_path / "Data")
    paths = app.state.delivery.paths
    monkeypatch.setattr("portable.runtime.feedback_admin.is_admin", lambda: False)
    with pytest.raises(PermissionError):
        issue(paths)
    monkeypatch.setattr("portable.runtime.feedback_admin.is_admin", lambda: True)
    token = issue(paths)
    assert authorized(paths, token)
    assert not authorized(paths, "wrong")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/operations/admin-config").status_code == 403
        assert client.post("/api/operations/configure", json={"enabled": False}).status_code == 403
        assert client.post("/api/operations/connection-test", json={}).status_code == 403
        assert (
            client.get(
                "/api/operations/admin-config", headers={"X-Feedback-Admin": token}
            ).status_code
            == 200
        )
        public = client.get("/api/operations/status").json()
        assert set(public["feedback"]["config"]) == {"enabled"}
        assert "Feedback Token" not in client.get("/field/assets/operations.js").text
        assert client.post("/api/operations/finish-day", json={}).json()["status"] == "LOCAL_ONLY"
        atomic_json(
            paths.state / "feedback-admin-session.json",
            {
                "sha256": hashlib.sha256(token.encode()).hexdigest(),
                "expires": time.time() - 1,
            },
        )
        assert (
            client.get(
                "/api/operations/admin-config", headers={"X-Feedback-Admin": token}
            ).status_code
            == 403
        )


@pytest.mark.parametrize("bad", ["not a key", "-----BEGIN PRIVATE KEY-----", ""])
def test_invalid_public_key_rejected(bad):
    with pytest.raises(ValueError, match="KEY_INVALID"):
        receiver_identity(bad)


def test_offline_end_day_retains_outbox(setup, monkeypatch):
    delivery, _, _ = setup

    def offline(*args):
        raise OSError("offline")

    monkeypatch.setattr("forecast_provider.feedback_sync.transport._post", offline)
    assert delivery.finish_day()["status"] == "SAVED_FOR_RETRY"
    assert delivery.status()["pending_outbox"] == 1


def test_provisioning_directory_excluded_from_source_release():
    from make_release import EXCLUDE_DIRS, ROOT, release_files

    assert "key" in EXCLUDE_DIRS
    assert all("key" not in path.relative_to(ROOT).parts for path in release_files())


def test_device_profiles_encrypted_and_selected_without_token_response(setup, monkeypatch):
    from portable.runtime.feedback_profiles import FeedbackProfiles

    delivery, config, _ = setup
    store = FeedbackProfiles(delivery.paths)
    entry = {k: config[k] for k in ("client_id", "token", "endpoint", "key_id", "public_key")}
    second = {**entry, "client_id": "SECOND", "token": "synthetic-second-token-" + "B" * 40}
    result = store.import_profiles(
        {"format": "bunsen-feedback-profiles-v1", "devices": [entry, second]}
    )
    assert config["token"] not in json.dumps(result)
    assert config["token"].encode() not in store.path.read_bytes()
    assert "token" not in result[0]
    monkeypatch.setattr(delivery, "connection_test", lambda: {"status": "CONNECTED"})
    restarted = FeedbackProfiles(delivery.paths)
    with pytest.raises(ValueError):
        restarted.apply(delivery, {"client_id": "SECOND"})
    assert (
        restarted.apply(delivery, {"client_id": "SECOND", "consent": True})["status"] == "CONNECTED"
    )
    assert delivery.token.load() == second["token"]
    assert delivery.config()["client_id"] == "SECOND"
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.import_profiles(
            {
                "format": "bunsen-feedback-profiles-v1",
                "devices": [entry, {**second, "public_key": "bad"}],
            }
        )
    assert store.path.read_bytes() == before
    with pytest.raises(ValueError):
        restarted.apply(delivery, {"client_id": "UNKNOWN", "consent": True})


def test_profiles_api_requires_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTABLE_SMOKE", "1")
    with TestClient(create_app(tmp_path / "Data"), base_url="http://127.0.0.1") as client:
        assert client.get("/api/operations/device-profiles").status_code == 403
        for action in ("profile-import", "profile-apply"):
            assert client.post("/api/operations/" + action, json={}).status_code == 403
