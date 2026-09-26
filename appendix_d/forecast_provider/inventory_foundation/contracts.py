"""Phase 3S-1 inventory foundationの固定codeと共通契約。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LocationType(StrEnum):
    FACTORY = "FACTORY"
    WAREHOUSE = "WAREHOUSE"


class RecommendationBasis(StrEnum):
    MINIMUM = "MINIMUM"
    STANDARD = "STANDARD"
    MAXIMUM = "MAXIMUM"


class SourceKind(StrEnum):
    CSV = "CSV"
    PDF_EXTRACTED = "PDF_EXTRACTED"


class NormalizedUnit(StrEnum):
    CASE = "CASE"


class BucketKind(StrEnum):
    EXPIRY_BUCKET = "EXPIRY_BUCKET"


class ProductIdentifierKind(StrEnum):
    JAN = "JAN"
    PRODUCT_CODE = "PRODUCT_CODE"


class SnapshotAtSourceKind(StrEnum):
    COLUMN = "COLUMN"
    FILENAME_YYYYMMDD = "FILENAME_YYYYMMDD"


class SnapshotDecisionType(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExtractionStatus(StrEnum):
    EXTRACTED = "EXTRACTED"
    VALIDATED = "VALIDATED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REVIEWED = "REVIEWED"
    FAILED = "FAILED"


class ExtractionReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InventoryIssueCode(StrEnum):
    EXPIRED_AT_SNAPSHOT = "EXPIRED_AT_SNAPSHOT"


class QuarantineReason(StrEnum):
    ROW_SHAPE_INVALID = "ROW_SHAPE_INVALID"
    JAN_MISSING = "JAN_MISSING"
    JAN_INVALID = "JAN_INVALID"
    PRODUCT_MAPPING_MISSING = "PRODUCT_MAPPING_MISSING"
    PRODUCT_MAPPING_AMBIGUOUS = "PRODUCT_MAPPING_AMBIGUOUS"
    LOCATION_MISSING = "LOCATION_MISSING"
    LOCATION_UNKNOWN = "LOCATION_UNKNOWN"
    LOCATION_AMBIGUOUS = "LOCATION_AMBIGUOUS"
    LOCATION_TYPE_INVALID = "LOCATION_TYPE_INVALID"
    EXPIRY_MISSING = "EXPIRY_MISSING"
    EXPIRY_INVALID = "EXPIRY_INVALID"
    QUANTITY_MISSING = "QUANTITY_MISSING"
    QUANTITY_INVALID = "QUANTITY_INVALID"
    QUANTITY_NEGATIVE = "QUANTITY_NEGATIVE"
    SNAPSHOT_AT_MISSING = "SNAPSHOT_AT_MISSING"
    SNAPSHOT_AT_INVALID = "SNAPSHOT_AT_INVALID"
    SNAPSHOT_AT_INCONSISTENT = "SNAPSHOT_AT_INCONSISTENT"
    UNIT_MAPPING_MISSING = "UNIT_MAPPING_MISSING"
    SOURCE_DUPLICATE = "SOURCE_DUPLICATE"
    PDF_EXTRACTION_NOT_APPROVED = "PDF_EXTRACTION_NOT_APPROVED"


class InventoryCsvErrorCode(StrEnum):
    EMPTY_SOURCE = "EMPTY_SOURCE"
    ENCODING_UNSUPPORTED = "ENCODING_UNSUPPORTED"
    DECODE_FAILED = "DECODE_FAILED"
    CSV_MALFORMED = "CSV_MALFORMED"
    HEADER_MISSING = "HEADER_MISSING"
    HEADER_DUPLICATE = "HEADER_DUPLICATE"
    REQUIRED_COLUMN_MISSING = "REQUIRED_COLUMN_MISSING"
    SNAPSHOT_SOURCE_REFERENCE_MISSING = "SNAPSHOT_SOURCE_REFERENCE_MISSING"
    SNAPSHOT_FILENAME_INVALID = "SNAPSHOT_FILENAME_INVALID"
    SNAPSHOT_TIME_POLICY_INVALID = "SNAPSHOT_TIME_POLICY_INVALID"


@dataclass(frozen=True)
class SnapshotIdentity:
    snapshot_id: str
    content_sha256: str


@dataclass(frozen=True)
class PdfApprovalReference:
    extraction_id: str
    review_id: str
    decision: ExtractionReviewDecision

    def __post_init__(self) -> None:
        if not self.extraction_id or not self.review_id:
            raise ValueError("PDF extraction IDとreview IDは必須です")
        if self.decision is not ExtractionReviewDecision.APPROVED:
            raise ValueError("承認済みPDF extractionだけを正式入力にできます")
