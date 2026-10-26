"""Pinned GitHub Portable releases; signed manifests and bounded ZIP staging."""

import base64
import hashlib
import json
import re
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from forecast_provider.update_service.github_release import API_URL, ASSET_PREFIX, _read
from portable import APP_VERSION
from portable.runtime.update_state import state_lock, write_state

TRUST_KEY = Path(__file__).parent / "release-update-public.pem"
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)-pilot\.(\d+)$")


def version(value):
    match = VERSION.fullmatch(value)
    if not match:
        raise ValueError("Portableの版番号が不正です")
    return tuple(map(int, match.groups()))


def verified(raw, signature, public_key):
    if len(raw) > 65536 or len(signature) > 8192:
        raise ValueError("更新情報が大きすぎます")

    def unique(pairs):
        value = {}
        for k, v in pairs:
            if k in value:
                raise ValueError("更新情報の重複項目")
            value[k] = v
        return value

    data = json.loads(raw, object_pairs_hook=unique)
    key = serialization.load_pem_public_key(public_key)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("署名公開鍵が不正です")
    key.verify(
        base64.b64decode(signature.strip(), validate=True),
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(),
    )
    if (
        set(data)
        != {
            "format",
            "version",
            "minimum_version",
            "package",
            "sha256",
            "size_bytes",
            "database_migration",
        }
        or data["format"] != "bunsen-portable-update-v1"
        or data["package"] != f"BunsenPortable-{data['version']}.zip"
        or not re.fullmatch("[0-9a-f]{64}", data["sha256"])
        or type(data["size_bytes"]) is not int
        or not 0 < data["size_bytes"] <= 500_000_000
        or type(data["database_migration"]) is not int
        or data["database_migration"] != 0
        or version(data["minimum_version"]) > version(APP_VERSION)
    ):
        raise ValueError("更新の形式・容量・対応バージョンを確認してください")
    version(data["version"])
    return data


def unpack(archive, target, manifest):
    """Extract allowlisted signed files only; never accept a bundled Data tree."""
    expected_root = "BunsenPortable-" + manifest["version"]
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if len(members) > 15000 or sum(m.file_size for m in members) > 2_000_000_000:
            raise ValueError("更新ZIPの展開サイズ超過")
        seen = set()
        files = []
        for member in members:
            parts = PurePosixPath(member.filename).parts
            if (
                not parts
                or parts[0] != expected_root
                or ".." in parts
                or "\\" in member.filename
                or ":" in member.filename
                or member.filename.startswith("/")
                or member.flag_bits & 1
                or stat.S_ISLNK(member.external_attr >> 16)
                or any(p.endswith((".", " ")) for p in parts)
                or any(
                    re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", p)
                    for p in parts
                )
                or member.file_size > 500_000_000
            ):
                raise ValueError("更新ZIPに不正なパスがあります")
            relative = "/".join(parts[1:])
            if relative.casefold() in seen or (
                len(parts) > 1 and parts[1].casefold() in {"data", "updates"}
            ):
                raise ValueError("更新ZIPに重複または業務データが含まれます")
            seen.add(relative.casefold())
            if not member.is_dir():
                files.append((member, relative))
        package = json.loads(source.read(expected_root + "/PACKAGE-MANIFEST.json"))
        if package["app_version"] != manifest["version"]:
            raise ValueError("内部バージョンが一致しません")
        expected = package["files"]
        if set(expected) != {r for _, r in files if r != "PACKAGE-MANIFEST.json"}:
            raise ValueError("内部ファイル一覧が一致しません")
        if "App/BunsenPortable.exe" not in expected:
            raise ValueError("起動ファイルがありません")
        for member, relative in files:
            raw = source.read(member)
            if (
                relative != "PACKAGE-MANIFEST.json"
                and hashlib.sha256(raw).hexdigest() != expected[relative]
            ):
                raise ValueError("更新ファイルのハッシュ不一致")
            output = target / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(raw)


class ReleaseUpdate:
    def __init__(self, install_root, *, fetch=_read, key_path=TRUST_KEY):
        self.root = Path(install_root)
        self.work = self.root / "Updates"
        self.work.mkdir(parents=True, exist_ok=True)
        self.fetch = fetch
        self.key_path = key_path
        self._status_error = None

    def status(self):
        if self._status_error:
            return dict(self._status_error)
        path = self.work / "status.json"
        try:
            with state_lock(path):
                value = (
                    json.loads(path.read_text("utf-8"))
                    if path.exists() else {"status": "NOT_CHECKED"}
                )
                if not isinstance(value, dict) or not isinstance(value.get("status"), str):
                    raise ValueError("Invalid update state")
                last = self.work / "last-apply.json"
                if last.exists():
                    value["last_apply"] = json.loads(last.read_text("utf-8"))
                return value
        except (OSError, ValueError):
            return {"status": "CHECK_FAILED", "reason": "STATE_READ_FAILED", "retryable": True}

    def record(self, **value):
        try:
            write_state(self.work / "status.json", value)
        except OSError:
            self._status_error = {
                "status": "CHECK_FAILED", "reason": "STATE_SAVE_FAILED", "retryable": True
            }
            return dict(self._status_error)
        self._status_error = None
        return value

    def check(self):
        if not self.key_path.is_file():
            return self.record(status="UNCONFIGURED")
        try:
            releases = json.loads(self.fetch(API_URL, 2_000_000))
            candidates = [
                r
                for r in releases
                if not r.get("draft")
                and str(r.get("tag_name", "")).startswith("portable-v")
                and VERSION.fullmatch(r["tag_name"][10:])
            ]
            if not candidates:
                return self.record(status="NO_RELEASE")
            release = max(candidates, key=lambda r: version(r["tag_name"][10:]))
            tag = release["tag_name"]
            assets = {a["name"]: a for a in release["assets"]}
            if len(assets) != len(release["assets"]):
                raise ValueError("配布ファイル名が重複しています")

            def url(name):
                expected = "https://github.com" + ASSET_PREFIX + tag + "/" + name
                if assets[name]["browser_download_url"] != expected:
                    raise ValueError("配布元が一致しません")
                return expected

            raw = self.fetch(url("portable-manifest.json"), 65536)
            signature = self.fetch(url("portable-manifest.sig"), 8192)
            manifest = verified(raw, signature, self.key_path.read_bytes())
            if tag != "portable-v" + manifest["version"]:
                raise ValueError("タグと版番号が一致しません")
            if version(manifest["version"]) <= version(APP_VERSION):
                return self.record(status="CURRENT")
            if assets[manifest["package"]]["size"] != manifest["size_bytes"]:
                raise ValueError("配布サイズが一致しません")
            write_state(
                self.work / "offer.json",
                {
                    "manifest": manifest,
                    "raw": raw.decode(),
                    "signature": signature.decode(),
                    "url": url(manifest["package"]),
                },
            )
            return self.record(status="AVAILABLE", version=manifest["version"])
        except Exception:
            return self.record(status="CHECK_FAILED")

    def stage(self):
        if self.status()["status"] != "AVAILABLE":
            raise ValueError("先に更新を確認してください")
        offer = json.loads((self.work / "offer.json").read_text("utf-8"))
        manifest = verified(
            offer["raw"].encode(), offer["signature"].encode(), self.key_path.read_bytes()
        )
        expected_url = (
            "https://github.com"
            + ASSET_PREFIX
            + "portable-v"
            + manifest["version"]
            + "/"
            + manifest["package"]
        )
        if offer["url"] != expected_url or version(manifest["version"]) <= version(APP_VERSION):
            raise ValueError("更新情報を再確認してください")
        raw = self.fetch(expected_url, manifest["size_bytes"])
        if (
            len(raw) != manifest["size_bytes"]
            or hashlib.sha256(raw).hexdigest() != manifest["sha256"]
        ):
            raise ValueError("ダウンロードした更新ファイルを検証できません")
        folder = self.work / ("staged-" + uuid.uuid4().hex)
        folder.mkdir()
        archive = folder / "package.zip"
        archive.write_bytes(raw)
        unpack(archive, folder / "package", manifest)
        write_state(folder / "offer.json", offer)
        result = self.record(status="STAGED", version=manifest["version"], stage=folder.name)
        if result["status"] != "STAGED":
            raise ValueError("更新状態を保存できませんでした。更新を確認して再試行してください")
        return result
