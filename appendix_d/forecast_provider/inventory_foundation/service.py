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
from .snapshot_time import SnapshotTimePolicy
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
    pilot_scope_version: str | None = None,
    pilot_intake_version: str | None = None,
) -> InventorySnapshotJob:
    if known_at.tzinfo is None or known_at.utcoffset() is None:
        raise ValueError("known_atはtimezone付き日時です")
    known_at = known_at.astimezone(UTC)
    payload = {
        "format": "inventory-snapshot-job-v1",
        "source_reference": source_reference,
        "source_sha256": source_sha256.lower(),
        "mapping_version": mapping_version,
        "known_at": known_at.isoformat(),
    }
    if (pilot_scope_version is None) != (pilot_intake_version is None):
        raise ValueError("Pilot ScopeとIntake versionは同時に指定してください")
    if pilot_scope_version is not None:
        payload.update(
            format="inventory-snapshot-job-v2-pilot",
            pilot_scope_version=pilot_scope_version,
            pilot_intake_version=pilot_intake_version,
        )
    job_id = _content_id("inventory-job", payload)
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
        pilot_scope_version=pilot_scope_version,
        pilot_intake_version=pilot_intake_version,
    )


class InventorySnapshotService:
    def prepare_finalization(
        self,
        lease: InventorySnapshotLease,
        content: bytes,
        mapping: InventoryInputMappingVersion,
        resolver: InventoryReferenceResolver,
        *,
        snapshot_time_policy: SnapshotTimePolicy | None = None,
        completed_at: datetime,
        pilot_scope=None,
        pilot_intake=None,
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
        parsed = parse_inventory_csv(
            content,
            mapping,
            source_reference=job.source_reference,
            snapshot_time_policy=snapshot_time_policy,
        )
        pilot_selection = None
        if (
            job.pilot_scope_version is not None
            or pilot_scope is not None
            or pilot_intake is not None
        ):
            if (
                pilot_scope is None
                or pilot_intake is None
                or job.pilot_scope_version != pilot_scope.version.pilot_scope_version
                or job.pilot_intake_version != pilot_intake.intake_version
                or pilot_intake.pilot_scope_version != job.pilot_scope_version
                or pilot_scope.version.created_at > job.known_at
                or pilot_intake.created_at > job.known_at
            ):
                raise InventorySnapshotProcessingError(
                    InventorySnapshotJobErrorCode.PILOT_INTAKE_INVALID
                )
            from ..pilot_scope.intake import select_pilot_rows

            pilot_selection = select_pilot_rows(parsed, mapping=mapping, binding=pilot_intake)
            parsed = pilot_selection.parsed
        validation = validate_inventory_csv(parsed, mapping, resolver)
        scope_reconciliation = None
        if pilot_selection is not None:
            from ..pilot_scope.domain import build_scope_reconciliation

            scoped_quantity = validation.reconciliation.normalized_quantity_cases
            scope_reconciliation = build_scope_reconciliation(
                source_sha256=job.source_sha256,
                source_row_count=pilot_selection.source_row_count,
                scoped_row_count=validation.reconciliation.accepted_row_count,
                out_of_scope_row_count=pilot_selection.out_of_scope_row_count,
                quarantined_scope_row_count=validation.reconciliation.quarantined_row_count,
                source_quantity_cases=(
                    validation.reconciliation.source_quantity_cases
                    + pilot_selection.out_of_scope_quantity_cases
                ),
                scoped_quantity_cases=scoped_quantity,
                out_of_scope_quantity_cases=pilot_selection.out_of_scope_quantity_cases,
                quarantined_scope_quantity_cases=(
                    validation.reconciliation.source_quantity_cases - scoped_quantity
                ),
            )
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
                pilot_scope_version=job.pilot_scope_version,
            )
            decision = SnapshotDecisionType.APPROVED
            reason = "CSV_STRICT_VALIDATION_APPROVED"
        if decision is SnapshotDecisionType.APPROVED:
            scoped_reference = None
            if pilot_selection is not None:
                from ..pilot_scope.domain import (
                    build_scoped_snapshot_reference,
                )

                scoped_reference = build_scoped_snapshot_reference(
                    inventory_snapshot=snapshot,
                    pilot_scope=pilot_scope,
                    reconciliation=scope_reconciliation,
                    recorded_at=completed_at,
                )
            return InventorySnapshotFinalization(
                validation=validation,
                snapshot=snapshot,
                completed_at=completed_at,
                pilot_scoped_reference=scoped_reference,
                pilot_reconciliation=scope_reconciliation,
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
            pilot_reconciliation=scope_reconciliation,
        )
