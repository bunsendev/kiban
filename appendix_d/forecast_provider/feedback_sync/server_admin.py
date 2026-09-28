"""中央側の鍵、Client許可Policy、保持期間を管理するオフラインCLI。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .server import FeedbackServerStore


def generate_keypair(private_path: Path, public_path: Path) -> None:
    if private_path.exists() or public_path.exists():
        raise ValueError("FEEDBACK_KEY_ALREADY_EXISTS")
    if private_path.parent.is_symlink() or public_path.parent.is_symlink():
        raise ValueError("FEEDBACK_KEY_PATH_INVALID")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
    descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(private)
    public_path.write_bytes(public)


def main() -> int:
    parser = argparse.ArgumentParser(description="Central feedback admin")
    actions = parser.add_subparsers(dest="action", required=True)
    keygen = actions.add_parser("keygen")
    keygen.add_argument("--private", type=Path, required=True)
    keygen.add_argument("--public", type=Path, required=True)
    enroll = actions.add_parser("enroll")
    enroll.add_argument("--db", type=Path, required=True)
    enroll.add_argument("--client-id", required=True)
    enroll.add_argument("--policy-version", required=True)
    enroll.add_argument("--policy-file", type=Path, required=True)
    grant = actions.add_parser("grant-support")
    grant.add_argument("--db", type=Path, required=True)
    grant.add_argument("--client-id", required=True)
    grant.add_argument("--consent-id", required=True)
    grant.add_argument("--sha256", required=True)
    grant.add_argument("--expires-at", required=True)
    grant.add_argument("--max-bytes", type=int, required=True)
    prune = actions.add_parser("prune")
    prune.add_argument("--db", type=Path, required=True)
    prune.add_argument("--diagnostic-days", type=int, default=30)
    prune.add_argument("--improvement-days", type=int, default=90)
    prune.add_argument("--support-days", type=int, default=7)
    args = parser.parse_args()
    if args.action == "keygen":
        generate_keypair(args.private, args.public)
        print("Key pair created. Protect the private key outside the package.")
    elif args.action == "enroll":
        token = sys.stdin.readline().strip()
        policy = json.loads(args.policy_file.read_text(encoding="utf-8"))
        FeedbackServerStore(args.db).enroll(args.client_id, token,
                                            args.policy_version, policy)
        print("Client policy enrolled.")
    elif args.action == "grant-support":
        FeedbackServerStore(args.db).grant_support(
            client_id=args.client_id, consent_id=args.consent_id,
            file_sha256=args.sha256, expires_at=datetime.fromisoformat(args.expires_at),
            max_bytes=args.max_bytes,
        )
        print("One-time support grant recorded.")
    else:
        count = FeedbackServerStore(args.db).prune({
            "DIAGNOSTIC": args.diagnostic_days,
            "IMPROVEMENT": args.improvement_days,
            "SUPPORT": args.support_days,
        })
        print(json.dumps({"deleted": count}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
