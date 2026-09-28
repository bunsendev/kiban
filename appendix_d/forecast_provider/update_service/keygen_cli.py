"""Generate a password-encrypted Ed25519 release signing key outside the repository."""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_key_pair(output: Path, password: bytes) -> tuple[Path, Path]:
    if len(password) < 16:
        raise ValueError("UPDATE_SIGNING_PASSWORD_TOO_SHORT")
    private_path = output / "release-update-private.pem"
    public_path = output / "release-update-public.pem"
    if private_path.exists() or public_path.exists():
        raise FileExistsError("UPDATE_SIGNING_KEY_ALREADY_EXISTS")
    output.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password),
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(private)
        with public_path.open("xb") as destination:
            destination.write(public)
    except BaseException:
        private_path.unlink(missing_ok=True)
        raise
    return private_path, public_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an encrypted Ed25519 release signing key",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    first = getpass.getpass("署名秘密鍵のパスフレーズ（16文字以上）: ")
    second = getpass.getpass("もう一度入力: ")
    if first != second:
        raise SystemExit("パスフレーズが一致しません")
    private, public = generate_key_pair(args.output_dir, first.encode("utf-8"))
    print(f"秘密鍵（暗号化済み）: {private}")
    print(f"公開鍵: {public}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
