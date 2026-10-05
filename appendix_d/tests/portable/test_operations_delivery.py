"""Consent, encryption, durable retries, signed updates and transactional rollback."""

import base64
import hashlib
import io
import json
import zipfile

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from fastapi.testclient import TestClient

from forecast_provider.feedback_sync.crypto import decrypt_package
from portable import APP_VERSION
from portable.api.app import create_app
from portable.api.field_store import FieldStore
from portable.runtime.feedback_delivery import FeedbackDelivery
from portable.runtime.paths import DataPaths
from portable.runtime.release_update import ReleaseUpdate, unpack, verified
from portable.runtime.update_apply import apply


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "credentials"))
    paths = DataPaths(tmp_path / "Data")
    paths.ensure()
    service = FeedbackDelivery(paths)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    service.configure(
        {
            "consent": True,
            "endpoint": "https://example.test/upload.php",
            "client_id": "synthetic",
            "token": "x" * 40,
            "public_key": pem,
        }
    )
    source = FieldStore(paths.state / "field-ui.sqlite3")
    source.feedback({"step": 1, "comment": "SENSITIVE synthetic comment"})
    return service, key, source


def test_encrypted_incremental_queue_and_comment_consent(delivery):
    service, key, source = delivery
    assert service.collect()
    assert not service.collect()
    item = service.store.pending(force=True)[0]
    assert b"SENSITIVE" not in item["envelope"]
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    _, value = decrypt_package(item["envelope"], private)
    assert value["payload"]["counts"] == {"help_feedback": 1}
    assert value["payload"]["comments"] == []
    assert "token" not in service.status()["config"]
    assert b"x" * 40 not in service.token.path.read_bytes()
    service.configure({**service.config(), "consent": True, "include_comments": True})
    assert service.store.pending(force=True) == []  # old consent queue quarantined
    source.feedback({"step": 2, "comment": "approved comment"})
    service.collect()
    item = service.store.pending(force=True)[0]
    _, value = decrypt_package(item["envelope"], private)
    assert value["payload"]["comments"] == [{"step": 2, "comment": "approved comment"}]


def test_retry_same_envelope_and_disabled_never_sends(delivery, monkeypatch):
    service, _, _ = delivery
    calls = []

    def network(request, timeout):
        calls.append(request.data)
        if len(calls) == 1:
            raise OSError("offline")
        envelope = json.loads(request.data)
        return {"ok": True, "status": "DUPLICATE", "request_id": envelope["package_id"]}

    monkeypatch.setattr("forecast_provider.feedback_sync.transport._post", network)
    service.send(manual=True)
    assert service.status()["pending_outbox"] == 1
    service.configure({"enabled": False})
    service.send(manual=True)
    assert len(calls) == 1
    service.configure({**service.config(), "consent": True, "enabled": True})
    service.send(manual=True)
    assert calls[0] == calls[1]
    assert service.status()["pending_outbox"] == 0
    assert service.status()["last_sync"]


def test_connection_test_has_no_business_payload(delivery, monkeypatch):
    service, key, _ = delivery
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )

    def receive(request, timeout):
        envelope, package = decrypt_package(request.data, private)
        assert package["category"] == "CONNECTION_TEST"
        assert package["payload"] == {}
        return {"ok": True, "status": "RECEIVED", "request_id": envelope["package_id"]}

    monkeypatch.setattr("forecast_provider.feedback_sync.transport._post", receive)
    assert service.connection_test()["status"] == "CONNECTED"
    assert not service.store.pending(force=True)


def test_large_comments_are_bounded_and_failed_ack_is_retained(delivery, monkeypatch):
    service, _, source = delivery
    service.configure({**service.config(), "consent": True, "include_comments": True})
    for _ in range(60):
        source.feedback({"step": 1, "comment": "あ" * 2000})
    monkeypatch.setattr(
        "forecast_provider.feedback_sync.transport._post",
        lambda *args: {"ok": True, "status": "RECEIVED", "request_id": "wrong"},
    )
    service.send(manual=True)
    assert len(service.store.pending(force=True)) == 2
    assert not service.status()["last_sync"]


def test_terminal_job_counts_omit_raw_exception(delivery):
    service, key, source = delivery
    source.put_job(
        {
            "id": "internal-job",
            "created_at": "now",
            "status": "FAILED",
            "message": "SECRET raw exception",
            "source": "customer.csv",
        }
    )
    service.collect()
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    _, payload = decrypt_package(service.store.pending(force=True)[0]["envelope"], private)
    assert payload["payload"]["counts"]["job_FAILED"] == 1
    assert "SECRET" not in json.dumps(payload)
    assert "customer.csv" not in json.dumps(payload)
    assert not service.collect()


def signed_release(tmp_path, extra=None):
    release = "99.0.0-pilot.1"
    files = {"App/BunsenPortable.exe": b"new app", "manual.txt": b"new manual"}
    files.update(extra or {})
    package = {
        "app_version": release,
        "files": {n: hashlib.sha256(v).hexdigest() for n, v in files.items()},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in files.items():
            z.writestr(f"BunsenPortable-{release}/{name}", data)
        z.writestr(f"BunsenPortable-{release}/PACKAGE-MANIFEST.json", json.dumps(package))
    archive = buffer.getvalue()
    key = ed25519.Ed25519PrivateKey.generate()
    public = tmp_path / "trusted.pem"
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    manifest = {
        "format": "bunsen-portable-update-v1",
        "version": release,
        "minimum_version": APP_VERSION,
        "package": f"BunsenPortable-{release}.zip",
        "sha256": hashlib.sha256(archive).hexdigest(),
        "size_bytes": len(archive),
        "database_migration": 0,
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    sig = base64.b64encode(key.sign(raw))
    from forecast_provider.update_service.github_release import API_URL, ASSET_PREFIX

    base = "https://github.com" + ASSET_PREFIX + "portable-v" + release + "/"
    assets = {
        "portable-manifest.json": raw,
        "portable-manifest.sig": sig,
        manifest["package"]: archive,
    }
    responses = {base + name: data for name, data in assets.items()}
    responses[API_URL] = json.dumps(
        [
            {
                "tag_name": "portable-v" + release,
                "assets": [
                    {"name": n, "size": len(d), "browser_download_url": base + n}
                    for n, d in assets.items()
                ],
            }
        ]
    ).encode()
    updater = ReleaseUpdate(tmp_path, fetch=lambda url, limit: responses[url], key_path=public)
    return updater, public, manifest, raw, sig, archive


def test_signed_update_switch_and_backup(tmp_path):
    updater, public, _, _, _, _ = signed_release(tmp_path)
    assert updater.check()["status"] == "AVAILABLE"
    stage = updater.stage()["stage"]
    (tmp_path / "App").mkdir()
    (tmp_path / "App/BunsenPortable.exe").write_bytes(b"old app")
    (tmp_path / "manual.txt").write_bytes(b"old manual")
    (tmp_path / "Data").mkdir()
    (tmp_path / "Data/business.txt").write_bytes(b"keep")
    calls = []
    apply(tmp_path, stage, public_key=public, smoke_test=lambda *args: calls.append(args))
    assert len(calls) == 2
    assert (tmp_path / "App/BunsenPortable.exe").read_bytes() == b"new app"
    assert (tmp_path / "Data/business.txt").read_bytes() == b"keep"
    assert (tmp_path / "manual.txt").read_bytes() == b"new manual"
    assert updater.status()["status"] == "UPDATED"
    assert list((tmp_path / "Updates").glob("apply-*/Data-backup.zip"))


def test_failed_actual_data_smoke_restores_app_and_data(tmp_path):
    updater, public, _, _, _, _ = signed_release(tmp_path)
    updater.check()
    stage = updater.stage()["stage"]
    (tmp_path / "App").mkdir()
    (tmp_path / "App/BunsenPortable.exe").write_bytes(b"old")
    (tmp_path / "Data").mkdir()
    (tmp_path / "Data/business.txt").write_bytes(b"keep")

    def fail(exe, data, version):
        if data == tmp_path / "Data":
            (data / "business.txt").write_bytes(b"changed")
            raise ValueError("synthetic smoke failure")

    with pytest.raises(ValueError, match="synthetic"):
        apply(tmp_path, stage, public_key=public, smoke_test=fail)
    assert (tmp_path / "App/BunsenPortable.exe").read_bytes() == b"old"
    assert (tmp_path / "Data/business.txt").read_bytes() == b"keep"
    assert updater.status()["status"] == "ROLLED_BACK"


@pytest.mark.parametrize("name", ["../escape", "Data/private.csv", "App/../../escape"])
def test_signed_unsafe_package_rejected(tmp_path, name):
    _updater, _, manifest, _, _, archive = signed_release(tmp_path, {name: b"bad"})
    target = tmp_path / "bad.zip"
    target.write_bytes(archive)
    with pytest.raises(ValueError):
        unpack(target, tmp_path / "out", manifest)


def test_tampered_signature_and_hash_fail_before_switch(tmp_path):
    updater, public, _, raw, sig, _ = signed_release(tmp_path)
    with pytest.raises(InvalidSignature):
        verified(raw.replace(b"99.0.0", b"98.0.0"), sig, public.read_bytes())
    updater.check()
    original = updater.fetch
    updater.fetch = lambda url, limit: b"wrong" if url.endswith(".zip") else original(url, limit)
    with pytest.raises(ValueError):
        updater.stage()
    assert not (tmp_path / "App").exists()


def test_operations_controls_require_same_origin_and_launcher(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTABLE_SMOKE", "1")
    app = create_app(tmp_path / "Data", control_token="control")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/operations/status").json()["feedback"]["config"]["enabled"] is False
        assert client.post("/api/control/finish-day").status_code == 403
        assert (
            client.post("/api/operations/update-apply", json={"confirm": True}).status_code == 422
        )
        assert (
            client.post(
                "/api/operations/configure",
                json={"enabled": False},
                headers={"origin": "https://evil.test"},
            ).status_code
            == 403
        )
        app.state.update_requested = "staged-test"
        assert client.post("/api/field/feedback", json={}).status_code == 503
