"""公開配布を模した人工データで更新の信頼境界を確認する。"""

import hashlib
import io
import json
import zipfile

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from forecast_provider.update_service.check_service import UpdateCheckService, UpdateCheckStore
from forecast_provider.update_service.download import download_verified
from forecast_provider.update_service.github_release import (
    API_URL,
    GitHubReleaseUpdateProvider,
)
from forecast_provider.update_service.keygen_cli import generate_key_pair
from forecast_provider.update_service.manifest import UpdateManifest, version_key
from forecast_provider.update_service.release_cli import prepare_release
from forecast_provider.update_service.release_preflight import inspect_public_package


def _keys():
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, public


def _package(tmp_path, version="0.1.0-field-pilot.4", *, forbidden=False):
    path = tmp_path / f"BunsenFieldPilot-{version}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("bin/app.py" if forbidden else "bin/app.exe", b"synthetic binary")
    return path


def test_version_contract_and_signed_manifest(tmp_path):
    assert version_key("0.1.0-field-pilot.3") < version_key("0.1.0-field-pilot.4")
    assert version_key("0.1.0-field-pilot.4") < version_key("0.1.0")
    assert version_key("0.1.0") < version_key("0.2.0")
    with pytest.raises(ValueError, match="UPDATE_VERSION_INVALID"):
        version_key("0.1.0-field-pilot.x")
    private, public = _keys()
    package = _package(tmp_path)
    output = tmp_path / "assets"
    prepare_release(package, output, version="0.1.0-field-pilot.4", channel="pilot",
                    minimum_version="0.1.0-field-pilot.3", database_migration=0,
                    notes=["取込の安定性を改善しました"], signing_key=private,
                    release_date="2026-09-28")
    manifest = UpdateManifest.parse((output / "manifest.json").read_bytes(),
                                    (output / "manifest.sig").read_bytes(), public)
    assert manifest.availability("0.1.0-field-pilot.3", "pilot") == "AVAILABLE"
    assert manifest.availability("0.1.0-field-pilot.4", "pilot") == "CURRENT"
    assert manifest.availability("0.1.0-field-pilot.2", "pilot") == "MANUAL_UPDATE_REQUIRED"
    assert manifest.availability("0.1.0-field-pilot.3", "stable") == "CHANNEL_MISMATCH"
    changed = json.loads((output / "manifest.json").read_bytes())
    changed["notes"] = ["改ざん"]
    with pytest.raises(InvalidSignature):
        UpdateManifest.parse(json.dumps(changed, ensure_ascii=False).encode(),
                             (output / "manifest.sig").read_bytes(), public)


def test_generated_encrypted_key_signs_release_and_cannot_be_overwritten(tmp_path):
    password = b"only-for-test-passphrase"
    private_path, public_path = generate_key_pair(tmp_path / "keys", password)
    assert b"ENCRYPTED PRIVATE KEY" in private_path.read_bytes()
    assert b"PRIVATE KEY" not in public_path.read_bytes()
    with pytest.raises(FileExistsError, match="UPDATE_SIGNING_KEY_ALREADY_EXISTS"):
        generate_key_pair(tmp_path / "keys", password)
    package = _package(tmp_path)
    output = tmp_path / "assets"
    prepare_release(package, output, version="0.1.0-field-pilot.4", channel="pilot",
                    minimum_version="0.1.0-field-pilot.3", database_migration=0,
                    notes=[], signing_key=private_path.read_bytes(), signing_password=password,
                    release_date="2026-09-29")
    UpdateManifest.parse((output / "manifest.json").read_bytes(),
                         (output / "manifest.sig").read_bytes(), public_path.read_bytes())


def test_public_package_preflight_blocks_source_and_secret(tmp_path):
    assert inspect_public_package(_package(tmp_path))["entry_count"] == 1
    with pytest.raises(ValueError, match="PUBLIC_PACKAGE_FORBIDDEN_CONTENT"):
        inspect_public_package(_package(tmp_path, forbidden=True))
    unsafe = tmp_path / "BunsenFieldPilot-0.1.0-field-pilot.5.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("bin/app.exe", b"github_pat_" + b"X" * 40)
    with pytest.raises(ValueError, match="PUBLIC_PACKAGE_SECRET_PATTERN"):
        inspect_public_package(unsafe)


def test_github_provider_uses_only_signed_assets_in_public_repo(tmp_path):
    private, public = _keys()
    package = _package(tmp_path)
    output = tmp_path / "assets"
    prepare_release(package, output, version="0.1.0-field-pilot.4", channel="pilot",
                    minimum_version="0.1.0-field-pilot.3", database_migration=0,
                    notes=[], signing_key=private, release_date="2026-09-28")
    base = "https://github.com/bunsendev/kiban-releases/releases/download/v0.1.0-field-pilot.4/"
    release = {"draft": False, "tag_name": "v0.1.0-field-pilot.4", "assets": [
        {"name": name, "browser_download_url": base + name,
         "size": path.stat().st_size}
        for name, path in (("manifest.json", output / "manifest.json"),
                           ("manifest.sig", output / "manifest.sig"),
                           (package.name, package))
    ]}
    data = {API_URL: json.dumps([release]).encode(),
            base + "manifest.json": (output / "manifest.json").read_bytes(),
            base + "manifest.sig": (output / "manifest.sig").read_bytes()}
    offer = GitHubReleaseUpdateProvider(fetcher=lambda url, limit: data[url]).check(
        current_version="0.1.0-field-pilot.3", channel="pilot", public_pem=public,
    )
    assert offer.status == "AVAILABLE"
    assert offer.package_url == base + package.name
    release["assets"][-1]["browser_download_url"] = "https://evil.example/package.zip"
    data[API_URL] = json.dumps([release]).encode()
    with pytest.raises(ValueError, match="UPDATE_ASSET_URL_INVALID"):
        GitHubReleaseUpdateProvider(fetcher=lambda url, limit: data[url]).check(
            current_version="0.1.0-field-pilot.3", channel="pilot", public_pem=public,
        )


class _Response:
    def __init__(self, body, status, headers=None):
        self.stream = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stream.close()

    def read(self, size):
        return self.stream.read(size)


def test_resume_download_requires_exact_range_and_hash(tmp_path):
    private, public = _keys()
    package = _package(tmp_path)
    output = tmp_path / "assets"
    prepare_release(package, output, version="0.1.0-field-pilot.4", channel="pilot",
                    minimum_version="0.1.0-field-pilot.3", database_migration=0,
                    notes=[], signing_key=private, release_date="2026-09-28")
    manifest = UpdateManifest.parse((output / "manifest.json").read_bytes(),
                                    (output / "manifest.sig").read_bytes(), public)
    body = package.read_bytes()
    root = tmp_path / "download"
    root.mkdir()
    (root / f"{manifest.package}.part").write_bytes(body[:20])
    url = ("https://github.com/bunsendev/kiban-releases/releases/download/"
           "v0.1.0-field-pilot.4/" + manifest.package)
    completed = download_verified(manifest, url, root, opener=lambda _url, offset: _Response(
        body[offset:], 206, {"Content-Range": f"bytes {offset}-{len(body)-1}/{len(body)}"},
    ))
    assert hashlib.sha256(completed.read_bytes()).hexdigest() == manifest.sha256
    assert completed == download_verified(manifest, url, root, opener=lambda *_: None)
    completed.unlink()
    with pytest.raises(ValueError, match="UPDATE_RESUME_NOT_SUPPORTED"):
        (root / f"{manifest.package}.part").write_bytes(body[:20])
        download_verified(manifest, url, root, opener=lambda *_: _Response(body, 200))


def test_check_is_cached_and_offline_does_not_block(tmp_path):
    _, public = _keys()
    key = tmp_path / "update-public.pem"
    key.write_bytes(public)
    store = UpdateCheckStore(tmp_path / "Inbox" / "update-checks.sqlite3")

    class Offline:
        calls = 0

        def check(self, **_):
            self.calls += 1
            raise TimeoutError("offline")

    provider = Offline()
    service = UpdateCheckService(store=store, current_version="0.1.0-field-pilot.3",
                                 channel="pilot", public_key_path=key, provider=provider)
    assert service.check(trigger="STARTUP")["last_check"]["status"] == "CHECK_FAILED"
    assert service.check(trigger="END_OF_DAY")["last_check"]["trigger"] == "STARTUP"
    assert provider.calls == 1
    assert service.check(trigger="MANUAL", force=True)["last_check"]["trigger"] == "MANUAL"
    assert provider.calls == 2


def test_unconfigured_check_never_contacts_github(tmp_path):
    class Unused:
        def check(self, **_):
            raise AssertionError("should not contact GitHub")

    service = UpdateCheckService(
        store=UpdateCheckStore(tmp_path / "update-checks.sqlite3"),
        current_version="0.1.0-field-pilot.3", channel="pilot",
        public_key_path=tmp_path / "absent.pem", provider=Unused(),
    )
    assert service.check(trigger="MANUAL", force=True)["last_check"]["status"] == "UNCONFIGURED"
