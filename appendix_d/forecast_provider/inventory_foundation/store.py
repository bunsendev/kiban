"""Phase 3S-1 inventory foundationのSQLite永続化。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .adapters import (
    InventoryExtraction,
    InventoryExtractionReview,
    InventorySourceDocument,
)
from .contracts import ExtractionReviewDecision, SourceKind
from .domain import (
    InventorySnapshot,
    canonical_datetime,
    canonical_decimal,
    verify_snapshot_identity,
)
from .locations import (
    InventoryLocation,
    LocationMasterVersion,
    RouteLeadTimePolicy,
    validate_route_locations,
)
from .mapping import InventoryInputMappingVersion


class SqliteInventoryFoundationStore:
    def __init__(self, path: Path):
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    def put_location_master(
        self,
        version: LocationMasterVersion,
        locations: list[InventoryLocation] | tuple[InventoryLocation, ...],
    ) -> None:
        if any(
            value.location_master_version != version.location_master_version
            for value in locations
        ):
            raise ValueError("locationは同じlocation master versionで指定してください")
        ids = [value.location_id for value in locations]
        codes = [value.location_code for value in locations]
        if len(ids) != len(set(ids)) or len(codes) != len(set(codes)):
            raise ValueError("location IDまたはcodeが重複しています")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO inventory_location_master_versions VALUES (?,?,?,?,?)",
                (
                    version.location_master_version,
                    version.content_sha256,
                    version.created_by,
                    version.reason,
                    canonical_datetime(version.created_at, "created_at"),
                ),
            )
            db.executemany(
                "INSERT INTO inventory_locations VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        value.location_master_version,
                        value.location_id,
                        value.location_code,
                        value.location_name,
                        value.location_type.value,
                        value.effective_from.isoformat(),
                        None if value.effective_to is None else value.effective_to.isoformat(),
                    )
                    for value in locations
                ],
            )

    def put_route_policy(self, value: RouteLeadTimePolicy) -> None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM inventory_locations WHERE location_master_version=? "
                "AND location_id IN (?,?)",
                (
                    value.location_master_version,
                    value.factory_location_id,
                    value.warehouse_location_id,
                ),
            ).fetchall()
            locations = tuple(
                InventoryLocation(
                    row["location_master_version"],
                    row["location_id"],
                    row["location_code"],
                    row["location_name"],
                    _location_type(row["location_type"]),
                    _date(row["effective_from"]),
                    None if row["effective_to"] is None else _date(row["effective_to"]),
                )
                for row in rows
            )
            validate_route_locations(value, locations)
            db.execute(
                "INSERT INTO inventory_route_lead_time_policies VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    value.policy_id,
                    value.policy_version,
                    value.location_master_version,
                    value.factory_location_id,
                    value.warehouse_location_id,
                    value.minimum_hours,
                    value.standard_hours,
                    value.maximum_hours,
                    value.recommendation_basis.value,
                    value.effective_from.isoformat(),
                    None if value.effective_to is None else value.effective_to.isoformat(),
                ),
            )

    def put_mapping(self, value: InventoryInputMappingVersion) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO inventory_input_mapping_versions VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    value.mapping_version,
                    value.product_column,
                    value.product_identifier_kind.value,
                    value.product_mapping_version,
                    value.location_column,
                    value.location_master_version,
                    value.expiry_column,
                    value.quantity_column,
                    value.snapshot_at_column,
                    value.source_quantity_column_name,
                    value.source_unit_label,
                    value.normalized_unit.value,
                    value.encoding,
                    value.delimiter,
                    value.header_row,
                    value.created_by,
                    value.reason,
                    canonical_datetime(value.created_at, "created_at"),
                ),
            )

    def put_source_document(self, value: InventorySourceDocument) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO inventory_source_documents VALUES (?,?,?,?,?)",
                (
                    value.document_id,
                    value.media_type,
                    value.archive_reference,
                    value.source_sha256,
                    canonical_datetime(value.created_at, "created_at"),
                ),
            )

    def put_extraction(self, value: InventoryExtraction) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO inventory_extractions VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    value.extraction_id,
                    value.document_id,
                    value.extractor_name,
                    value.extractor_version,
                    value.config_sha256,
                    value.output_reference,
                    value.output_sha256,
                    value.status.value,
                    canonical_datetime(value.created_at, "created_at"),
                ),
            )

    def put_extraction_review(self, value: InventoryExtractionReview) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status FROM inventory_extractions WHERE extraction_id=?",
                (value.extraction_id,),
            ).fetchone()
            if row is None:
                raise ValueError("PDF extractionが存在しません")
            if row["status"] not in {"VALIDATED", "REVIEW_REQUIRED", "REVIEWED"}:
                raise ValueError("validation済みPDF extractionだけを確認できます")
            db.execute(
                "INSERT INTO inventory_extraction_reviews VALUES (?,?,?,?,?,?)",
                (
                    value.review_id,
                    value.extraction_id,
                    value.decision.value,
                    value.reviewed_by,
                    value.reason,
                    canonical_datetime(value.reviewed_at, "reviewed_at"),
                ),
            )
            db.execute(
                "UPDATE inventory_extractions SET status='REVIEWED' WHERE extraction_id=?",
                (value.extraction_id,),
            )

    def put_snapshot(self, value: InventorySnapshot, *, job_id: str | None = None) -> None:
        verify_snapshot_identity(value)
        header = value.header
        approval = header.pdf_approval
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            mapping = db.execute(
                "SELECT location_master_version FROM inventory_input_mapping_versions "
                "WHERE mapping_version=?",
                (header.mapping_version,),
            ).fetchone()
            if mapping is None:
                raise ValueError("inventory input mappingが存在しません")
            if mapping["location_master_version"] != header.location_master_version:
                raise ValueError("snapshotとmappingのlocation master versionが一致しません")
            if header.source_kind is SourceKind.PDF_EXTRACTED:
                row = db.execute(
                    "SELECT r.decision,e.status FROM inventory_extraction_reviews r "
                    "JOIN inventory_extractions e ON e.extraction_id=r.extraction_id "
                    "WHERE r.extraction_id=? AND r.review_id=?",
                    (approval.extraction_id, approval.review_id),
                ).fetchone()
                if (
                    row is None
                    or row["decision"] != ExtractionReviewDecision.APPROVED.value
                    or row["status"] != "REVIEWED"
                ):
                    raise ValueError("未承認PDF extractionから正式snapshotは作成できません")
            db.execute(
                "INSERT INTO inventory_snapshots VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    header.snapshot_id,
                    job_id,
                    canonical_datetime(header.snapshot_at, "snapshot_at"),
                    canonical_datetime(header.known_at, "known_at"),
                    header.source_kind.value,
                    header.source_reference,
                    header.source_sha256,
                    header.mapping_version,
                    header.location_master_version,
                    header.product_mapping_version,
                    header.normalized_unit.value,
                    header.row_count,
                    canonical_decimal(header.quantity_cases_total),
                    header.content_sha256,
                    canonical_datetime(header.created_at, "created_at"),
                    None if approval is None else approval.extraction_id,
                    None if approval is None else approval.review_id,
                    None if approval is None else approval.decision.value,
                ),
            )
            db.executemany(
                "INSERT INTO inventory_expiry_buckets VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        header.snapshot_id,
                        header.location_master_version,
                        bucket.jan,
                        bucket.canonical_product_id,
                        bucket.location_id,
                        bucket.expiry_date.isoformat(),
                        bucket.bucket_kind.value,
                        canonical_decimal(bucket.quantity_cases),
                        bucket.normalized_unit.value,
                        json.dumps(
                            [code.value for code in bucket.issue_codes],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                    for bucket in value.buckets
                ],
            )

    def list_expiry_buckets(self, snapshot_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT jan,canonical_product_id,location_id,expiry_date,bucket_kind,"
                "quantity_cases,normalized_unit,issue_codes_json "
                "FROM inventory_expiry_buckets WHERE snapshot_id=? "
                "ORDER BY jan,location_id,expiry_date,normalized_unit",
                (snapshot_id,),
            )
            result = [dict(row) for row in rows]
        for row in result:
            row["issue_codes"] = json.loads(row.pop("issue_codes_json"))
        return result


def _location_type(value: str):
    from .contracts import LocationType

    return LocationType(value)


def _date(value):
    from datetime import date

    return value if isinstance(value, date) else date.fromisoformat(value)
