"""Phase 3S-1: 賞味期限bucketを保持する在庫基盤domain/schema。"""

from .adapters import (
    InventoryExtraction,
    InventoryExtractionReview,
    InventoryInputAdapter,
    InventorySourceDocument,
)
from .contracts import (
    BucketKind,
    ExtractionReviewDecision,
    ExtractionStatus,
    InventoryIssueCode,
    LocationType,
    NormalizedUnit,
    PdfApprovalReference,
    ProductIdentifierKind,
    QuarantineReason,
    RecommendationBasis,
    SnapshotDecisionType,
    SourceKind,
)
from .domain import (
    InventoryExpiryBucket,
    InventorySnapshot,
    InventorySnapshotHeader,
    build_inventory_snapshot,
    canonical_datetime,
    canonical_decimal,
    validate_jan,
    verify_snapshot_identity,
)
from .locations import (
    InventoryLocation,
    LocationMasterVersion,
    RouteLeadTimePolicy,
    validate_route_locations,
)
from .mapping import InventoryInputMappingVersion
from .postgres import PostgresInventoryFoundationStore
from .store import SqliteInventoryFoundationStore

__all__ = [
    "BucketKind",
    "ExtractionReviewDecision",
    "ExtractionStatus",
    "InventoryExpiryBucket",
    "InventoryExtraction",
    "InventoryExtractionReview",
    "InventoryInputAdapter",
    "InventoryInputMappingVersion",
    "InventoryIssueCode",
    "InventoryLocation",
    "InventorySnapshot",
    "InventorySnapshotHeader",
    "InventorySourceDocument",
    "LocationMasterVersion",
    "LocationType",
    "NormalizedUnit",
    "PdfApprovalReference",
    "PostgresInventoryFoundationStore",
    "ProductIdentifierKind",
    "QuarantineReason",
    "RecommendationBasis",
    "RouteLeadTimePolicy",
    "SnapshotDecisionType",
    "SourceKind",
    "SqliteInventoryFoundationStore",
    "build_inventory_snapshot",
    "canonical_datetime",
    "canonical_decimal",
    "validate_jan",
    "validate_route_locations",
    "verify_snapshot_identity",
]
