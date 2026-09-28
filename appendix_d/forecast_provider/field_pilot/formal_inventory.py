"""承認済みのField Pilot契約だけを正式在庫Snapshotジョブへ接続する。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..inventory_foundation.service import create_inventory_snapshot_job
from .inbox_classifier import Classification

INVENTORY_KINDS = frozenset({"WAREHOUSE_INVENTORY", "FACTORY_INVENTORY"})


@dataclass(frozen=True)
class QueuedInventoryJob:
    job_id: str


class FormalInventorySubmission:
    def __init__(self, inventory_store, pilot_scope_store, archive_root: Path, *,
                 clock=None):
        self.inventory_store = inventory_store
        self.pilot_scope_store = pilot_scope_store
        if archive_root.is_symlink():
            raise ValueError("ARCHIVE_PATH_INVALID")
        archive_root.mkdir(exist_ok=True)
        self.archive_root = archive_root.resolve(strict=True)
        self.clock = clock or (lambda: datetime.now(UTC))

    def __call__(self, classification: Classification, archive: Path,
                 reference: str, digest: str) -> QueuedInventoryJob | bool:
        if classification.kind not in INVENTORY_KINDS:
            return False
        if not all((classification.mapping_version, classification.pilot_scope_version,
                    classification.pilot_intake_version)):
            return False
        mapping = self.inventory_store.get_mapping(classification.mapping_version)
        scope = self.pilot_scope_store.get(classification.pilot_scope_version)
        intake = self.pilot_scope_store.get_intake(classification.pilot_intake_version)
        if (mapping is None or scope is None or intake is None
                or intake.mapping_version != mapping.mapping_version
                or intake.pilot_scope_version != scope.version.pilot_scope_version):
            return False
        if archive.is_symlink():
            return False
        path = archive.resolve(strict=True)
        if not path.is_file():
            return False
        try:
            path.relative_to(self.archive_root)
        except ValueError:
            return False
        relative = Path(reference)
        if relative.is_absolute() or ".." in relative.parts:
            return False
        try:
            expected_path = (self.archive_root / relative).resolve(strict=True)
        except (OSError, ValueError):
            return False
        if expected_path != path:
            return False
        known_at = self.clock().astimezone(UTC)
        if known_at < scope.version.created_at or known_at < intake.created_at:
            return False
        job = create_inventory_snapshot_job(
            source_reference=reference,
            source_sha256=digest,
            mapping_version=mapping.mapping_version,
            requested_by="FIELD_PILOT_INBOX",
            known_at=known_at,
            requested_at=known_at,
            pilot_scope_version=scope.version.pilot_scope_version,
            pilot_intake_version=intake.intake_version,
        )
        self.inventory_store.put_job(job)
        return QueuedInventoryJob(job.job_id)
