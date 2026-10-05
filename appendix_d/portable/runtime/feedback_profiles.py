"""Administrator-imported device presets, encrypted for the current Windows user."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from forecast_provider.feedback_sync.transport import _endpoint
from portable.runtime.api_credentials import protect, validate
from portable.runtime.feedback_delivery import receiver_identity


class FeedbackProfiles:
    def __init__(self, paths):
        identity = hashlib.sha256(str(paths.root).encode()).hexdigest()[:24]
        self.path = (
            Path(os.environ["LOCALAPPDATA"])
            / "Bunsen/Portable/Credentials"
            / ("profiles-" + identity + ".dpapi")
        )

    def load(self):
        if not self.path.exists():
            return {}
        if self.path.stat().st_size > 131072:
            raise ValueError("PROFILE_INVALID")
        return json.loads(protect(self.path.read_bytes(), decrypt=True))

    def summaries(self):
        return [
            {k: v[k] for k in ("client_id", "endpoint", "key_id", "key_fingerprint")}
            for _, v in sorted(self.load().items())
        ]

    def import_profiles(self, value):
        # Validate the entire batch before changing any stored configuration.
        if not isinstance(value, dict) or value.get("format") != "bunsen-feedback-profiles-v1":
            raise ValueError("PROFILE_INVALID")
        entries = value.get("devices")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 20:
            raise ValueError("PROFILE_INVALID")
        incoming = {}
        for item in entries:
            if not isinstance(item, dict) or set(item) != {
                "client_id",
                "token",
                "endpoint",
                "key_id",
                "public_key",
            }:
                raise ValueError("PROFILE_INVALID")
            device = item["client_id"]
            key_id = item["key_id"]
            if not isinstance(device, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", device):
                raise ValueError("PROFILE_INVALID")
            if not isinstance(key_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", key_id):
                raise ValueError("PROFILE_INVALID")
            if device in incoming:
                raise ValueError("PROFILE_DUPLICATE")
            validate(item["token"])
            _endpoint(item["endpoint"], item["token"])
            fingerprint = receiver_identity(item["public_key"])
            incoming[device] = {**item, "key_fingerprint": fingerprint}
        stored = self.load()
        stored.update(incoming)
        encrypted = protect(json.dumps(stored).encode())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encrypted)
            os.replace(temporary, self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return self.summaries()

    def apply(self, delivery, value):
        profile = self.load().get(value.get("client_id"))
        if profile is None:
            raise ValueError("PROFILE_NOT_FOUND")
        delivery.configure(
            {
                **profile,
                "enabled": True,
                "consent": value.get("consent") is True,
                "include_comments": value.get("include_comments") is True,
                "confirm_key_change": value.get("confirm_key_change") is True,
            }
        )
        return delivery.connection_test()
