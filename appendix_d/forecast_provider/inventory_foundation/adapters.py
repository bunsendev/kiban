"""CSV/PDFをcoreから分離する入力adapter境界。parserはPhase 3S-1対象外。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .contracts import (
    ExtractionReviewDecision,
    ExtractionStatus,
    PdfApprovalReference,
    SourceKind,
)


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label}は必須です")
    return normalized


def _sha(value: str, label: str) -> str:
    normalized = value.lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{label}は64文字のSHA-256 hexadecimalで指定してください")
    return normalized


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label}はtimezone付き日時で指定してください")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class InventorySourceDocument:
    document_id: str
    media_type: str
    archive_reference: str
    source_sha256: str
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("document_id", "media_type", "archive_reference"):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        object.__setattr__(self, "source_sha256", _sha(self.source_sha256, "source_sha256"))
        object.__setattr__(self, "created_at", _utc(self.created_at, "created_at"))


@dataclass(frozen=True)
class InventoryExtraction:
    extraction_id: str
    document_id: str
    extractor_name: str
    extractor_version: str
    config_sha256: str
    output_reference: str
    output_sha256: str
    status: ExtractionStatus
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "extraction_id",
            "document_id",
            "extractor_name",
            "extractor_version",
            "output_reference",
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        object.__setattr__(self, "config_sha256", _sha(self.config_sha256, "config_sha256"))
        object.__setattr__(self, "output_sha256", _sha(self.output_sha256, "output_sha256"))
        if not isinstance(self.status, ExtractionStatus):
            raise ValueError("extraction statusが不正です")
        object.__setattr__(self, "created_at", _utc(self.created_at, "created_at"))


@dataclass(frozen=True)
class InventoryExtractionReview:
    review_id: str
    extraction_id: str
    decision: ExtractionReviewDecision
    reviewed_by: str
    reason: str
    reviewed_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("review_id", "extraction_id", "reviewed_by", "reason"):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        if not isinstance(self.decision, ExtractionReviewDecision):
            raise ValueError("review decisionが不正です")
        object.__setattr__(self, "reviewed_at", _utc(self.reviewed_at, "reviewed_at"))

    def approval_reference(self) -> PdfApprovalReference:
        return PdfApprovalReference(self.extraction_id, self.review_id, self.decision)


class InventoryInputAdapter(Protocol):
    """後続Phaseが実装する構造化入力adapter。"""

    @property
    def source_kind(self) -> SourceKind: ...

    def rows(self) -> Iterable[Mapping[str, object]]: ...
