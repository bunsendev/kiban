"""Phase 3S-3 inventory snapshot job、lease、finalization契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .contracts import SnapshotDecisionType, SourceKind
from .domain import InventorySnapshot
from .validation import InventoryCsvValidationResult


class InventorySnapshotJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class InventorySnapshotJobErrorCode(StrEnum):
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_REFERENCE_INVALID = "SOURCE_REFERENCE_INVALID"
    SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
    SOURCE_SHA256_MISMATCH = "SOURCE_SHA256_MISMATCH"
    CSV_CONTRACT_FAILED = "CSV_CONTRACT_FAILED"
    MAPPING_NOT_FOUND = "MAPPING_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"


class StaleInventorySnapshotLeaseError(RuntimeError):
    pass


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label}はtimezone付き日時です")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class InventorySnapshotJob:
    job_id: str
    source_kind: SourceKind
    source_reference: str
    source_sha256: str
    mapping_version: str
    requested_by: str
    status: InventorySnapshotJobStatus
    accepted_row_count: int
    quarantined_row_count: int
    error_code: str | None
    known_at: datetime
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt: int = 0
    worker_id: str | None = None
    lease_token: str | None = None
    leased_until: datetime | None = None
    last_heartbeat_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("job_id", "source_reference", "mapping_version", "requested_by"):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name}は必須です")
            object.__setattr__(self, field_name, value)
        source_sha256 = self.source_sha256.lower()
        if len(source_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in source_sha256
        ):
            raise ValueError("source_sha256が不正です")
        object.__setattr__(self, "source_sha256", source_sha256)
        if self.source_kind is not SourceKind.CSV:
            raise ValueError("Phase 3S-3 jobはCSVだけを処理します")
        if not isinstance(self.status, InventorySnapshotJobStatus):
            raise ValueError("statusが不正です")
        for name in ("accepted_row_count", "quarantined_row_count", "attempt"):
            value = getattr(self, name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name}は0以上です")
        object.__setattr__(self, "known_at", _aware(self.known_at, "known_at"))
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        for name in ("started_at", "finished_at", "leased_until", "last_heartbeat_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _aware(value, name))
        lease_values = (self.worker_id, self.lease_token, self.leased_until)
        if self.status is InventorySnapshotJobStatus.RUNNING and any(
            value is None for value in lease_values
        ):
            raise ValueError("RUNNING jobにはworker、token、lease期限が必要です")
        if self.status is not InventorySnapshotJobStatus.RUNNING and any(
            value is not None for value in lease_values
        ):
            raise ValueError("RUNNING以外のjobにactive leaseは指定できません")


@dataclass(frozen=True)
class InventorySnapshotLease:
    job: InventorySnapshotJob
    worker_id: str
    lease_token: str
    leased_until: datetime

    def __post_init__(self) -> None:
        if not self.worker_id.strip() or not self.lease_token.strip():
            raise ValueError("worker_idとlease_tokenは必須です")
        if self.job.status is not InventorySnapshotJobStatus.RUNNING:
            raise ValueError("RUNNING jobだけをleaseにできます")
        if self.job.worker_id != self.worker_id or self.job.lease_token != self.lease_token:
            raise ValueError("jobとleaseのfencing情報が一致しません")
        object.__setattr__(self, "leased_until", _aware(self.leased_until, "leased_until"))


@dataclass(frozen=True)
class InventorySnapshotFinalization:
    validation: InventoryCsvValidationResult
    snapshot: InventorySnapshot | None
    completed_at: datetime
    decision_id: str | None = None
    decision_version: str | None = None
    decision: SnapshotDecisionType | None = None
    decided_by: str | None = None
    reason: str | None = None
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "completed_at", _aware(self.completed_at, "completed_at"))
        decision_values = (
            self.decision_id,
            self.decision_version,
            self.decision,
            self.decided_by,
            self.reason,
            self.decided_at,
        )
        if self.decision is None:
            if any(value is not None for value in decision_values):
                raise ValueError("decision未指定時はdecision metadataを指定できません")
            if self.snapshot is None or not self.validation.approval_ready:
                raise ValueError("技術的生成完了には採用可能なvalidationとsnapshotが必要です")
            return
        if any(value is None for value in decision_values):
            raise ValueError("decision指定時はdecision metadataがすべて必要です")
        for name in ("decision_id", "decision_version", "decided_by", "reason"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name}は必須です")
        object.__setattr__(self, "decided_at", _aware(self.decided_at, "decided_at"))
        if self.decision is SnapshotDecisionType.APPROVED:
            raise ValueError("業務APPROVEDはsnapshot生成後の追記型判断として登録します")
        if self.decision is not SnapshotDecisionType.REJECTED:
            raise ValueError("自動decisionはREJECTEDだけを指定できます")
        if self.snapshot is not None or self.validation.approval_ready:
            raise ValueError("REJECTEDには不採用validationだけを指定します")
