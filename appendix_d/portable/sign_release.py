"""Offline signing only; never uploads releases or accepts a password argument."""

import argparse
import base64
import getpass
import hashlib
import json
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from portable import APP_VERSION
from portable.runtime.release_update import unpack, version


def sign(package, private_key, password, minimum_version, output):
    release = package.stem.removeprefix("BunsenPortable-")
    version(release)
    if version(minimum_version) > version(release):
        raise ValueError("minimum_version must not exceed release")
    key = serialization.load_pem_private_key(private_key.read_bytes(), password=password)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Ed25519 signing key required")
    value = {
        "format": "bunsen-portable-update-v1",
        "version": release,
        "minimum_version": minimum_version,
        "package": package.name,
        "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "size_bytes": package.stat().st_size,
        "database_migration": 0,
    }
    with tempfile.TemporaryDirectory() as tmp:
        unpack(package, Path(tmp), value)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    output.mkdir(parents=True, exist_ok=True)
    # Refuse accidental replacement of an already signed release.
    if any((output / n).exists() for n in ("portable-manifest.json", "portable-manifest.sig")):
        raise ValueError("Signed files already exist; choose a new output directory")
    (output / "portable-manifest.json").write_bytes(raw)
    (output / "portable-manifest.sig").write_bytes(base64.b64encode(key.sign(raw)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--minimum-version", default=APP_VERSION)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    password = getpass.getpass("署名秘密鍵のパスフレーズ（画面・ログに表示しません）: ")
    sign(args.package, args.private_key, password.encode(), args.minimum_version, args.output)
    print("署名ファイルを作成しました。秘密鍵を配布しないでください。")


if __name__ == "__main__":
    main()
