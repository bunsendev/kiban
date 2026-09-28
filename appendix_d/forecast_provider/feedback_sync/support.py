"""原本は一度限りの両側許可があるサポートPackageに限る。"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .crypto import encrypt_package
from .policy import FeedbackStore

MAX_SUPPORT_BYTES = 5_000_000


def queue_support(store: FeedbackStore, *, consent_id: str, source: Path,
                  client_id: str, destination: str, public_key: bytes) -> str:
    if (source.is_symlink() or not source.is_file()
            or source.suffix.lower() not in {".csv", ".pdf"}
            or not 0 < source.stat().st_size <= MAX_SUPPORT_BYTES):
        raise ValueError("SUPPORT_SOURCE_INVALID")
    content = source.read_bytes()
    if len(content) > MAX_SUPPORT_BYTES:
        raise ValueError("SUPPORT_SOURCE_TOO_LARGE")
    if not store.use_consent(consent_id, target=source.name, destination=destination):
        raise ValueError("SUPPORT_CONSENT_MISSING_OR_EXPIRED")
    with store._db() as db:
        consent = db.execute("SELECT expires_at,purpose FROM consents WHERE consent_id=?",
                             (consent_id,)).fetchone()
    package_id = uuid.uuid4().hex
    package = {
        "category": "SUPPORT",
        "manifest": {
            "consent_id": consent_id,
            "expires_at": consent["expires_at"],
            "created_at": datetime.now(UTC).isoformat(),
            "contains_raw_files": True,
            "file_sha256": hashlib.sha256(content).hexdigest(),
            "file_size": len(content),
            "file_name": source.name,
            "purpose": consent["purpose"],
        },
        "payload": {"file_base64": base64.b64encode(content).decode()},
    }
    envelope = encrypt_package(package, public_key, package_id=package_id,
                               client_id=client_id)
    store.queue(package_id, f"support:{consent_id}", envelope)
    return package_id


def validate_support(package: dict) -> tuple[str, str, bytes]:
    if not isinstance(package, dict) or set(package) != {"category", "manifest", "payload"}:
        raise ValueError("SUPPORT_PACKAGE_INVALID")
    manifest, payload = package["manifest"], package["payload"]
    if (package["category"] != "SUPPORT" or not isinstance(manifest, dict)
            or set(manifest) != {"consent_id", "expires_at", "created_at",
                                 "contains_raw_files", "file_sha256", "file_size",
                                 "file_name", "purpose"}
            or manifest["contains_raw_files"] is not True
            or not isinstance(payload, dict) or set(payload) != {"file_base64"}
            or not isinstance(manifest["file_name"], str)
            or Path(manifest["file_name"]).name != manifest["file_name"]
            or Path(manifest["file_name"]).suffix.lower() not in {".csv", ".pdf"}
            or not isinstance(manifest["purpose"], str)
            or not 1 <= len(manifest["purpose"]) <= 300):
        raise ValueError("SUPPORT_PACKAGE_INVALID")
    if (not isinstance(manifest["consent_id"], str)
            or len(manifest["consent_id"]) != 32
            or any(c not in "0123456789abcdef" for c in manifest["consent_id"])):
        raise ValueError("SUPPORT_PACKAGE_INVALID")
    expires = datetime.fromisoformat(manifest["expires_at"])
    if expires.tzinfo is None or datetime.now(UTC) >= expires:
        raise ValueError("SUPPORT_CONSENT_EXPIRED")
    content = base64.b64decode(payload["file_base64"], validate=True)
    if (not 0 < len(content) <= MAX_SUPPORT_BYTES
            or manifest["file_size"] != len(content)
            or hashlib.sha256(content).hexdigest() != manifest["file_sha256"]):
        raise ValueError("SUPPORT_CONTENT_INVALID")
    return manifest["consent_id"], manifest["file_sha256"], content
