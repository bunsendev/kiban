"""標準AEADと受信者公開鍵による送信Envelope。"""

from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt_package(package: dict, public_pem: bytes, *, package_id: str,
                    client_id: str) -> bytes:
    public = serialization.load_pem_public_key(public_pem)
    if not isinstance(public, rsa.RSAPublicKey) or public.key_size < 3072:
        raise ValueError("FEEDBACK_PUBLIC_KEY_INVALID")
    plain = json.dumps(package, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
    limit = 7_500_000 if package.get("category") == "SUPPORT" else 1_000_000
    if len(plain) > limit:
        raise ValueError("FEEDBACK_PACKAGE_TOO_LARGE")
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    aad = f"{client_id}:{package_id}".encode("ascii")
    ciphertext = AESGCM(key).encrypt(nonce, plain, aad)
    wrapped = public.encrypt(key, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None,
    ))
    envelope = {"format": "bunsen-feedback-v1", "client_id": client_id,
                "package_id": package_id, "nonce": base64.b64encode(nonce).decode(),
                "wrapped_key": base64.b64encode(wrapped).decode(),
                "ciphertext": base64.b64encode(ciphertext).decode(),
                "sha256": hashlib.sha256(ciphertext).hexdigest()}
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()


def decrypt_package(envelope_bytes: bytes, private_pem: bytes) -> tuple[dict, dict]:
    if len(envelope_bytes) > 10_000_000:
        raise ValueError("FEEDBACK_ENVELOPE_TOO_LARGE")
    envelope = json.loads(envelope_bytes)
    if envelope.get("format") != "bunsen-feedback-v1":
        raise ValueError("FEEDBACK_ENVELOPE_INVALID")
    ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
    if hashlib.sha256(ciphertext).hexdigest() != envelope.get("sha256"):
        raise ValueError("FEEDBACK_ENVELOPE_HASH_MISMATCH")
    private = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(private, rsa.RSAPrivateKey) or private.key_size < 3072:
        raise ValueError("FEEDBACK_PRIVATE_KEY_INVALID")
    key = private.decrypt(base64.b64decode(envelope["wrapped_key"], validate=True),
                          padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                       algorithm=hashes.SHA256(), label=None))
    plain = AESGCM(key).decrypt(base64.b64decode(envelope["nonce"], validate=True),
                                ciphertext,
                                f"{envelope['client_id']}:{envelope['package_id']}".encode("ascii"))
    return envelope, json.loads(plain)
