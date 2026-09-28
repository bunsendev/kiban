"""公開Releaseの署名済み更新契約。SHAは破損検出、署名は発行元検証。"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(field-pilot)\.(0|[1-9]\d*))?$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PACKAGE = re.compile(r"^BunsenFieldPilot-[0-9A-Za-z.-]+\.zip$")
FORMAT = "kiban-field-pilot-update-v1"
CHANNELS = frozenset({"pilot", "stable"})
MAX_MANIFEST_BYTES = 65_536
MAX_NOTES = 5


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("UPDATE_MANIFEST_DUPLICATE_KEY")
        result[key] = value
    return result


def version_key(value: str) -> tuple[int, int, int, int, int]:
    matched = VERSION.fullmatch(value)
    if matched is None:
        raise ValueError("UPDATE_VERSION_INVALID")
    major, minor, patch = (int(matched.group(index)) for index in (1, 2, 3))
    # SemVer: prerelease precedes the matching stable release.
    stable = 0 if matched.group(4) else 1
    sequence = int(matched.group(5)) if matched.group(5) else 0
    return major, minor, patch, stable, sequence


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    channel: str
    minimum_version: str
    package: str
    sha256: str
    size_bytes: int
    requires_restart: bool
    database_migration: int
    release_date: str
    critical: bool
    notes: tuple[str, ...]

    @classmethod
    def parse(cls, raw: bytes, signature: bytes, public_pem: bytes) -> UpdateManifest:
        if not 0 < len(raw) <= MAX_MANIFEST_BYTES:
            raise ValueError("UPDATE_MANIFEST_SIZE_INVALID")
        try:
            document = json.loads(raw, object_pairs_hook=_unique_pairs)
            if not isinstance(document, dict) or set(document) != {
                "format", "version", "channel", "minimum_version", "package",
                "sha256", "size_bytes", "requires_restart", "database_migration",
                "release_date", "critical", "notes",
            }:
                raise ValueError("UPDATE_MANIFEST_INVALID")
            canonical = json.dumps(document, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8")
            key = serialization.load_pem_public_key(public_pem)
            if not isinstance(key, Ed25519PublicKey):
                raise ValueError("UPDATE_SIGNING_KEY_INVALID")
            key.verify(base64.b64decode(signature.strip(), validate=True), canonical)
            if (document["format"] != FORMAT
                    or document["channel"] not in CHANNELS
                    or not PACKAGE.fullmatch(document["package"])
                    or PurePosixPath(document["package"]).name != document["package"]
                    or not SHA256.fullmatch(document["sha256"])
                    or type(document["size_bytes"]) is not int
                    or not 0 < document["size_bytes"] <= 1_000_000_000
                    or type(document["database_migration"]) is not int
                    or not 0 <= document["database_migration"] <= 10_000
                    or type(document["requires_restart"]) is not bool
                    or type(document["critical"]) is not bool
                    or not isinstance(document["notes"], list)
                    or len(document["notes"]) > MAX_NOTES
                    or any(not isinstance(note, str) or not 1 <= len(note) <= 160
                           for note in document["notes"])):
                raise ValueError("UPDATE_MANIFEST_INVALID")
            version_key(document["version"])
            version_key(document["minimum_version"])
            date.fromisoformat(document["release_date"])
            if version_key(document["minimum_version"]) > version_key(document["version"]):
                raise ValueError("UPDATE_MANIFEST_VERSION_RANGE")
            return cls(**{key: value for key, value in document.items()
                          if key not in {"format", "notes"}},
                       notes=tuple(document["notes"]))
        except (UnicodeError, json.JSONDecodeError, TypeError, KeyError, OverflowError) as exc:
            raise ValueError("UPDATE_MANIFEST_INVALID") from exc

    def availability(self, current_version: str, channel: str) -> str:
        if channel != self.channel or channel not in CHANNELS:
            return "CHANNEL_MISMATCH"
        current = version_key(current_version)
        if current >= version_key(self.version):
            return "CURRENT"
        if current < version_key(self.minimum_version):
            return "MANUAL_UPDATE_REQUIRED"
        return "AVAILABLE"
