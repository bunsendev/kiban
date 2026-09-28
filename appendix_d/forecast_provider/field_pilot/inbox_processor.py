"""Windowsで安定確認済みの原本だけを不変保管・分類・既存取込へ渡す。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path, PureWindowsPath

from .formal_inventory import QueuedInventoryJob
from .improvement_events import ImprovementEventLedger
from .inbox_classifier import Classification, classify_file
from .inbox_ledger import InboxLedger
from .inbox_policy import InboxPolicy

MAX_META_BYTES = 4_096
MAX_FILE_BYTES = 2_000_000_000
logger = logging.getLogger("kiban.field_pilot.inbox")
ValidatedImport = Callable[[Classification, Path, str, str], bool | QueuedInventoryJob]
ReviewObserver = Callable[[Classification, Path, str], str | None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class InboxProcessor:
    def __init__(
        self, root: Path, policy: InboxPolicy, ledger: InboxLedger,
        validated_import: ValidatedImport | None = None,
        review_observer: ReviewObserver | None = None,
        improvement_events: ImprovementEventLedger | None = None,
    ):
        self.root = root.resolve(strict=True)
        self.policy = policy
        self.ledger = ledger
        self.validated_import = validated_import
        self.review_observer = review_observer
        self.improvement_events = improvement_events
        archive = self.root / "Archive"
        if archive.is_symlink():
            raise ValueError("ARCHIVE_PATH_INVALID")
        archive.mkdir(exist_ok=True)

    def scan(self) -> int:
        count = 0
        staging = self.root / "Staged"
        if not staging.is_dir() or staging.is_symlink():
            return 0
        for manifest in sorted(staging.glob("*.json")):
            self._process(manifest)
            count += 1
        return count

    def _process(self, manifest: Path) -> None:
        stage_id = manifest.stem
        if len(stage_id) != 32 or any(char not in "0123456789abcdef" for char in stage_id):
            return
        source = manifest.with_suffix(".bin")
        if manifest.is_symlink() or source.is_symlink() or not source.is_file():
            return
        if self.ledger.has_stage(stage_id):
            source.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
            return
        if manifest.stat().st_size > MAX_META_BYTES:
            return
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            name = meta["original_name"]
            digest = meta["sha256"]
            size = meta["size_bytes"]
            received_at = meta["received_at"]
            if (
                not isinstance(name, str) or name in {"", ".", ".."} or len(name) > 240
                or PureWindowsPath(name).name != name or "/" in name
                or not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                or isinstance(size, bool) or not isinstance(size, int)
                or not 0 < size <= MAX_FILE_BYTES
                or not isinstance(received_at, str) or len(received_at) > 40
                or source.stat().st_size != size or _sha256(source) != digest
            ):
                return
        except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
            return
        archive = self._archive(source, digest, name)
        reference = archive.relative_to(self.root / "Archive").as_posix()
        classification = classify_file(archive, name, self.policy)
        status = classification.status
        reason = classification.reason
        formal_job_id = None
        if self.ledger.has_hash(digest, self.policy.version):
            status, reason = "DUPLICATE", "SAME_SHA256"
        elif status == "CONFIRMED" and self.ledger.has_previous(classification, digest):
            status, reason = "REVISION_CANDIDATE", "SAME_TARGET_DIFFERENT_SHA256"
        elif status == "CONFIRMED":
            status, reason = "RECEIVED", "VALIDATED_IMPORT_NOT_CONFIGURED"
            if self.validated_import is not None:
                try:
                    result = self.validated_import(classification, archive, reference, digest)
                    if isinstance(result, QueuedInventoryJob):
                        status, reason = "RECEIVED", "INVENTORY_JOB_QUEUED"
                        formal_job_id = result.job_id
                    elif result is True:
                        status, reason = "PROCESSED", "STRICT_VALIDATION_SUCCEEDED"
                    else:
                        status, reason = "REVIEW_REQUIRED", "STRICT_VALIDATION_NOT_READY"
                except Exception:
                    status, reason = "REVIEW_REQUIRED", "STRICT_VALIDATION_FAILED"
        elif status in {"UNKNOWN", "REVIEW_REQUIRED"} and self.review_observer:
            try:
                self.review_observer(classification, archive, reference)
            except (OSError, ValueError):
                reason = "LEARNING_CANDIDATE_UNAVAILABLE"
        self.ledger.record(
            stage_id=stage_id, sha256=digest,
            source_name_sha256=hashlib.sha256(name.encode("utf-8")).hexdigest(),
            size_bytes=size, status=status, reason=reason,
            classification=classification, policy_version=self.policy.version,
            archive_reference=reference, received_at=received_at,
            formal_job_id=formal_job_id,
        )
        if self.improvement_events is not None:
            event_type = (
                "INBOX_DUPLICATE" if status == "DUPLICATE"
                else "INBOX_VALIDATED" if status == "PROCESSED"
                else "INBOX_REVIEW" if status in {
                    "REVIEW_REQUIRED", "REVISION_CANDIDATE", "UNKNOWN", "REJECTED"
                }
                else "INBOX_CLASSIFIED"
            )
            try:
                self.improvement_events.append(
                    event_type,
                    outcome="OK" if status in {"PROCESSED", "RECEIVED", "DUPLICATE"}
                    else "REVIEW",
                    business_date=date.fromisoformat(classification.target_date)
                    if classification.target_date else None,
                    location_id=classification.location_id,
                    policy_version=self.policy.version,
                    schema_version=classification.schema_id,
                    metrics={"size_bytes": size},
                    error_code=reason,
                )
            except (OSError, ValueError, sqlite3.DatabaseError):
                logger.warning("field pilot improvement event unavailable")
        source.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)

    def _archive(self, source: Path, digest: str, name: str) -> Path:
        target = self.root / "Archive" / digest[:2] / digest / name
        if (self.root / "Archive" / digest[:2]).is_symlink() or target.parent.is_symlink():
            raise ValueError("ARCHIVE_PATH_INVALID")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_symlink() or _sha256(target) != digest:
                raise ValueError("ARCHIVE_CHECKSUM_MISMATCH")
            return target
        temporary = target.parent / f".{uuid.uuid4().hex}.tmp"
        try:
            with source.open("rb") as reader, temporary.open("xb") as writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            if _sha256(temporary) != digest:
                raise ValueError("ARCHIVE_CHECKSUM_MISMATCH")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target
