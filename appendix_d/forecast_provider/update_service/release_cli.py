"""公開配布候補の検査・Manifest生成・署名。秘密鍵は引数の外部ファイルだけ。"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .manifest import FORMAT, UpdateManifest, version_key
from .release_preflight import inspect_public_package


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_release(package: Path, output: Path, *, version: str, channel: str,
                    minimum_version: str, database_migration: int,
                    notes: list[str], signing_key: bytes | None = None,
                    signing_password: bytes | None = None,
                    release_date: str | None = None) -> dict:
    version_key(version)
    version_key(minimum_version)
    if version_key(minimum_version) > version_key(version):
        raise ValueError("UPDATE_MANIFEST_VERSION_RANGE")
    if channel not in {"pilot", "stable"} or not 0 <= database_migration <= 10_000:
        raise ValueError("UPDATE_RELEASE_INPUT_INVALID")
    if len(notes) > 5 or any(not isinstance(note, str) or not 1 <= len(note) <= 160
                             for note in notes):
        raise ValueError("UPDATE_RELEASE_NOTES_INVALID")
    expected = f"BunsenFieldPilot-{version}.zip"
    if package.name != expected:
        raise ValueError("UPDATE_PACKAGE_NAME_INVALID")
    inspection = inspect_public_package(package)
    manifest = {
        "format": FORMAT, "version": version, "channel": channel,
        "minimum_version": minimum_version, "package": expected,
        "sha256": _sha256(package),
        "size_bytes": package.stat().st_size, "requires_restart": True,
        "database_migration": database_migration,
        "release_date": release_date or datetime.now(UTC).date().isoformat(),
        "critical": False, "notes": notes,
    }
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    if signing_key is not None:
        key = serialization.load_pem_private_key(signing_key, password=signing_password)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("UPDATE_SIGNING_KEY_INVALID")
        signature = base64.b64encode(key.sign(canonical))
        UpdateManifest.parse(canonical, signature, key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_bytes(canonical + b"\n")
    (output / "SHA256SUMS.txt").write_text(
        f"{manifest['sha256']}  {expected}\n", encoding="ascii",
    )
    if signing_key is not None:
        (output / "manifest.sig").write_bytes(signature + b"\n")
    return {"version": version, "package": expected, **inspection,
            "signed": signing_key is not None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=["pilot", "stable"], required=True)
    parser.add_argument("--minimum-version", required=True)
    parser.add_argument("--database-migration", type=int, required=True)
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--signing-key-file", type=Path)
    args = parser.parse_args()
    key = args.signing_key_file.read_bytes() if args.signing_key_file else None
    password = None
    if key is not None and b"ENCRYPTED PRIVATE KEY" in key:
        password = getpass.getpass("署名秘密鍵のパスフレーズ: ").encode("utf-8")
    result = prepare_release(
        args.package, args.output, version=args.version, channel=args.channel,
        minimum_version=args.minimum_version,
        database_migration=args.database_migration, notes=args.note, signing_key=key,
        signing_password=password,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
