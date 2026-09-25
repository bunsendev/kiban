"""CSV validation結果から正式snapshotと追記型decisionを決定する。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from .contracts import SnapshotDecisionType, SourceKind
from .csv_adapter import parse_inventory_csv
from .domain import build_inventory_snapshot
from .job_contracts import (
    InventorySnapshotFinalization,
    InventorySnapshotJob,
    InventorySnapshotJobErrorCode,
    InventorySnapshotJobStatus,
    InventorySnapshotLease,
)
from .mapping import InventoryInputMappingVersion
from .references import InventoryReferenceResolver
from .validation import validate_inventory_csv


class InventorySnapshotProcessingError(RuntimeError):
    def __init__(self, code: InventorySnapshotJobErrorCode):
        self.code = code
        super().__init__(code.value)


def _content_id(prefix: str, payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()}"


def create_inventory_snapshot_job(
    *,
    source_reference: str,
    source_sha256: str,
    mapping_version: str,
    requested_by: str,
    known_at: datetime,
    requested_at: datetime,
) -> InventorySnapshotJob:
    if known_at.tzinfo is None or known_at.utcoffset() is None:
        raise ValueError("known_atはtimezone付き日時です")
    known_at = known_at.astimezone(UTC)
    job_id = _content_id(
        "inventory-job",
        {
            "format": "inventory-snapshot-job-v1",
            "source_reference": source_reference,
            "source_sha256": source_sha256.lower(),
            "mapping_version": mapping_version,
            "known_at": known_at.isoformat(),
        },
    )
    return InventorySnapshotJob(
        job_id,
        SourceKind.CSV,
        source_reference,
        source_sha256,
        mapping_version,
        requested_by,
        InventorySnapshotJobStatus.QUEUED,
        0,
        0,
        None,
        known_at,
        requested_at,
    )


class InventorySnapshotService:
    def prepare_finalization(
        self,
        lease: InventorySnapshotLease,
        content: bytes,
        mapping: InventoryInputMappingVersion,
        resolver: InventoryReferenceResolver,
        *,
        completed_at: datetime,
    ) -> InventorySnapshotFinalization:
        job = lease.job
        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("completed_atはtimezone付き日時です")
        completed_at = completed_at.astimezone(UTC)
        if hashlib.sha256(content).hexdigest() != job.source_sha256:
            raise InventorySnapshotProcessingError(
                InventorySnapshotJobErrorCode.SOURCE_SHA256_MISMATCH
            )
        if mapping.mapping_version != job.mapping_version:
            raise InventorySnapshotProcessingError(InventorySnapshotJobErrorCode.MAPPING_NOT_FOUND)
        parsed = parse_inventory_csv(content, mapping)
        validation = validate_inventory_csv(parsed, mapping, resolver)
        snapshot = None
        decision = SnapshotDecisionType.REJECTED
        reason = "CSV_VALIDATION_REJECTED"
        if validation.approval_ready:
            assert validation.snapshot_at is not None
            snapshot = build_inventory_snapshot(
                snapshot_at=validation.snapshot_at,
                known_at=job.known_at,
                source_kind=job.source_kind,
                source_reference=job.source_reference,
                source_sha256=job.source_sha256,
                mapping_version=job.mapping_version,
                location_master_version=mapping.location_master_version,
                product_mapping_version=mapping.product_mapping_version or "JAN-DIRECT-v1",
                buckets=validation.buckets,
                created_at=completed_at,
            )
            decision = SnapshotDecisionType.APPROVED
            reason = "CSV_STRICT_VALIDATION_APPROVED"
        if decision is SnapshotDecisionType.APPROVED:
            return InventorySnapshotFinalization(
                validation=validation,
                snapshot=snapshot,
                completed_at=completed_at,
            )
        payload = {
            "format": "inventory-snapshot-decision-v1",
            "job_id": job.job_id,
            "decision": decision.value,
            "snapshot_id": None if snapshot is None else snapshot.header.snapshot_id,
        }
        decision_id = _content_id("inventory-decision", payload)
        return InventorySnapshotFinalization(
            validation=validation,
            snapshot=None,
            completed_at=completed_at,
            decision_id=decision_id,
            decision_version=decision_id,
            decision=decision,
            decided_by="SYSTEM:inventory-snapshot-worker",
            reason=reason,
            decided_at=completed_at,
        )
