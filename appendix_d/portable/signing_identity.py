"""Local release signing identity; encrypted key and current-user DPAPI password."""

import argparse
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from portable.runtime.api_credentials import ApiCredentials


def create(directory: Path):
    directory.mkdir(parents=True, exist_ok=False)
    password = secrets.token_urlsafe(48)
    credentials = ApiCredentials(directory / "passphrase.dpapi")
    credentials.save(password)
    if credentials.load() != password:
        raise ValueError("署名資格情報の保存を確認できません")
    key = Ed25519PrivateKey.generate()
    (directory / "release-update-private.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password.encode()),
        )
    )
    (directory / "release-update-public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    create(args.output_dir)
    print("署名鍵とWindows暗号化資格情報を保存しました。")


if __name__ == "__main__":
    main()
