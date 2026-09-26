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
from .contracts import (
    ExtractionReviewDecision,
    NormalizedUnit,
    ProductIdentifierKind,
    SourceKind,
)
from .domain import (
    InventorySnapshot,
    canonical_datetime,
    canonical_decimal,
    verify_snapshot_identity,
)
from .job_store import InventorySnapshotJobStoreMixin, _datetime
from .location_store import InventoryLocationStoreMixin
from .mapping import InventoryInputMappingVersion
from .product_mapping_store import InventoryProductMappingStoreMixin


class SqliteInventoryFoundationStore(
    InventoryLocationStoreMixin,
    InventoryProductMappingStoreMixin,
    InventorySnapshotJobStoreMixin,
):
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
            self._upgrade_job_columns(db)
            self._upgrade_decision_revision(db)
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
            self._upgrade_quarantine_reasons(db)
            self._upgrade_decision_revision(db)

    @staticmethod
    def _upgrade_decision_revision(db) -> None:
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='inventory_snapshot_decisions'"
        ).fetchone()
        if table is None:
            return
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(inventory_snapshot_decisions)")
        }
        if "revision" not in columns:
            db.execute("ALTER TABLE inventory_snapshot_decisions ADD COLUMN revision INTEGER")
            rows = db.execute(
                "SELECT decision_id,snapshot_id,job_id FROM inventory_snapshot_decisions "
                "ORDER BY decided_at,decision_id"
            ).fetchall()
            revisions: dict[str, int] = {}
            for row in rows:
                key = row[1] or f"job:{row[2]}"
                revisions[key] = revisions.get(key, 0) + 1
                db.execute(
                    "UPDATE inventory_snapshot_decisions SET revision=? WHERE decision_id=?",
                    (revisions[key], row[0]),
                )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS inventory_snapshot_decisions_revision_idx "
            "ON inventory_snapshot_decisions(snapshot_id,revision) "
            "WHERE snapshot_id IS NOT NULL"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS inventory_snapshot_decisions_state_idx "
            "ON inventory_snapshot_decisions(decision,snapshot_id,revision)"
        )

    @staticmethod
    def _upgrade_job_columns(db) -> None:
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='inventory_snapshot_jobs'"
        ).fetchone()
        if table is None:
            return
        columns = {row[1] for row in db.execute("PRAGMA table_info(inventory_snapshot_jobs)")}
        additions = {
            "known_at": "TIMESTAMPTZ",
            "attempt": "INTEGER NOT NULL DEFAULT 0",
            "worker_id": "TEXT",
            "lease_token": "TEXT",
            "leased_until": "TIMESTAMPTZ",
            "last_heartbeat_at": "TIMESTAMPTZ",
        }
        for name, definition in additions.items():
            if name not in columns:
                db.execute(f"ALTER TABLE inventory_snapshot_jobs ADD COLUMN {name} {definition}")
        db.execute(
            "UPDATE inventory_snapshot_jobs SET known_at=requested_at WHERE known_at IS NULL"
        )
        db.execute(
            "UPDATE inventory_snapshot_jobs SET status='QUEUED',error_code=NULL "
            "WHERE status='RUNNING' AND (worker_id IS NULL OR lease_token IS NULL "
            "OR leased_until IS NULL)"
        )

    @staticmethod
    def _upgrade_quarantine_reasons(db) -> None:
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='inventory_snapshot_quarantines'"
        ).fetchone()
        if row is None or "ROW_SHAPE_INVALID" in row[0]:
            return
        db.execute("PRAGMA foreign_keys=OFF")
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "ALTER TABLE inventory_snapshot_quarantines "
                "RENAME TO inventory_snapshot_quarantines_phase3s1"
            )
            db.execute(
                "CREATE TABLE inventory_snapshot_quarantines ("
                "quarantine_id TEXT PRIMARY KEY,"
                "job_id TEXT NOT NULL REFERENCES inventory_snapshot_jobs(job_id),"
                "source_reference TEXT NOT NULL,"
                "row_number INTEGER NOT NULL CHECK(row_number >= 1),"
                "row_sha256 TEXT NOT NULL CHECK(length(row_sha256)=64),"
                "reason_code TEXT NOT NULL CHECK(reason_code IN ("
                "'ROW_SHAPE_INVALID','JAN_MISSING','JAN_INVALID',"
                "'PRODUCT_MAPPING_MISSING','PRODUCT_MAPPING_AMBIGUOUS',"
                "'LOCATION_MISSING','LOCATION_UNKNOWN','LOCATION_AMBIGUOUS',"
                "'LOCATION_TYPE_INVALID','EXPIRY_MISSING','EXPIRY_INVALID',"
                "'QUANTITY_MISSING','QUANTITY_INVALID','QUANTITY_NEGATIVE',"
                "'SNAPSHOT_AT_MISSING','SNAPSHOT_AT_INVALID',"
                "'SNAPSHOT_AT_INCONSISTENT','UNIT_MAPPING_MISSING',"
                "'SOURCE_DUPLICATE','PDF_EXTRACTION_NOT_APPROVED')),"
                "created_at TIMESTAMPTZ NOT NULL,"
                "UNIQUE(job_id,source_reference,row_number,reason_code))"
            )
            db.execute(
                "INSERT INTO inventory_snapshot_quarantines "
                "SELECT * FROM inventory_snapshot_quarantines_phase3s1"
            )
            db.execute("DROP TABLE inventory_snapshot_quarantines_phase3s1")
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        finally:
            db.execute("PRAGMA foreign_keys=ON")

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

    def get_mapping(self, mapping_version: str) -> InventoryInputMappingVersion | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM inventory_input_mapping_versions WHERE mapping_version=?",
                (mapping_version,),
            ).fetchone()
        if row is None:
            return None
        return InventoryInputMappingVersion(
            row["mapping_version"],
            row["product_column"],
            ProductIdentifierKind(row["product_identifier_kind"]),
            row["product_mapping_version"],
            row["location_column"],
            row["location_master_version"],
            row["expiry_column"],
            row["quantity_column"],
            row["snapshot_at_column"],
            row["source_quantity_column_name"],
            row["source_unit_label"],
            NormalizedUnit(row["normalized_unit"]),
            row["encoding"],
            row["delimiter"],
            row["header_row"],
            row["created_by"],
            row["reason"],
            _datetime(row["created_at"]),
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
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._insert_snapshot(db, value, job_id=job_id)

    @staticmethod
    def _insert_snapshot(db, value: InventorySnapshot, *, job_id: str | None) -> None:
        verify_snapshot_identity(value)
        header = value.header
        approval = header.pdf_approval
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

    def list_snapshots(self, job_id: str | None = None) -> list[dict]:
        sql = (
            "SELECT snapshot_id,job_id,snapshot_at,known_at,source_kind,source_sha256,"
            "mapping_version,location_master_version,product_mapping_version,"
            "normalized_unit,row_count,quantity_cases_total,content_sha256,created_at "
            "FROM inventory_snapshots"
        )
        params = ()
        if job_id is not None:
            sql += " WHERE job_id=?"
            params = (job_id,)
        sql += " ORDER BY snapshot_at,snapshot_id"
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, params)]

    def list_expiry_buckets_with_location(self, snapshot_id: str) -> list[dict]:
        """Phase 3T向けにlocation typeを保持したFEFO順read modelを返す。"""

        with self._connect() as db:
            rows = db.execute(
                "SELECT b.jan,b.canonical_product_id,b.location_id,l.location_code,"
                "l.location_type,b.expiry_date,b.bucket_kind,b.quantity_cases,"
                "b.normalized_unit,b.issue_codes_json FROM inventory_expiry_buckets b "
                "JOIN inventory_locations l ON l.location_master_version=b.location_master_version "
                "AND l.location_id=b.location_id WHERE b.snapshot_id=? "
                "ORDER BY b.jan,b.location_id,b.expiry_date,b.normalized_unit",
                (snapshot_id,),
            )
            result = [dict(row) for row in rows]
        for row in result:
            row["issue_codes"] = json.loads(row.pop("issue_codes_json"))
        return result

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT snapshot_id,job_id,snapshot_at,known_at,source_kind,source_sha256,"
                "mapping_version,location_master_version,product_mapping_version,"
                "normalized_unit,row_count,quantity_cases_total,content_sha256,created_at "
                "FROM inventory_snapshots WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def quarantine_summary(self, job_id: str) -> list[dict]:
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT reason_code,COUNT(*) AS row_count "
                    "FROM inventory_snapshot_quarantines WHERE job_id=? "
                    "GROUP BY reason_code ORDER BY reason_code",
                    (job_id,),
                )
            ]

    def list_snapshots_page(
        self,
        *,
        limit: int,
        offset: int,
        decision_status: str | None = None,
    ) -> tuple[int, list[dict]]:
        latest = (
            "LEFT JOIN inventory_snapshot_decisions d ON d.snapshot_id=s.snapshot_id "
            "AND d.revision=(SELECT MAX(d2.revision) FROM inventory_snapshot_decisions d2 "
            "WHERE d2.snapshot_id=s.snapshot_id) "
        )
        where = ""
        params: list[object] = []
        if decision_status == "UNREVIEWED":
            where = "WHERE d.decision IS NULL "
        elif decision_status is not None:
            where = "WHERE d.decision=? "
            params.append(decision_status)
        with self._connect() as db:
            total = db.execute(
                "SELECT COUNT(*) AS value FROM inventory_snapshots s " + latest + where,
                tuple(params),
            ).fetchone()["value"]
            rows = db.execute(
                "SELECT s.snapshot_id,s.job_id,s.snapshot_at,s.known_at,s.source_kind,"
                "s.mapping_version,s.location_master_version,s.product_mapping_version,"
                "s.normalized_unit,s.row_count,s.quantity_cases_total,s.content_sha256,"
                "s.created_at,d.decision AS current_decision,d.revision AS decision_revision "
                "FROM inventory_snapshots s "
                + latest
                + where
                + "ORDER BY s.snapshot_at DESC,s.snapshot_id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return total, [dict(row) for row in rows]

    def list_expiry_buckets_page(
        self,
        snapshot_id: str,
        *,
        limit: int,
        offset: int,
        jan: str | None = None,
        location_id: str | None = None,
        location_type: str | None = None,
    ) -> tuple[int, list[dict]]:
        clauses = ["b.snapshot_id=?"]
        params: list[object] = [snapshot_id]
        for column, value in (
            ("b.jan", jan),
            ("b.location_id", location_id),
            ("l.location_type", location_type),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(value)
        where = " AND ".join(clauses)
        joined = (
            " FROM inventory_expiry_buckets b JOIN inventory_locations l "
            "ON l.location_master_version=b.location_master_version "
            "AND l.location_id=b.location_id WHERE " + where
        )
        with self._connect() as db:
            total = db.execute(
                "SELECT COUNT(*) AS value" + joined, tuple(params)
            ).fetchone()["value"]
            rows = db.execute(
                "SELECT b.jan,b.canonical_product_id,b.location_id,l.location_code,"
                "l.location_type,b.expiry_date,b.bucket_kind,b.quantity_cases,"
                "b.normalized_unit,b.issue_codes_json"
                + joined
                + " ORDER BY b.jan,b.location_id,b.expiry_date,b.normalized_unit "
                "LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["issue_codes"] = json.loads(row.pop("issue_codes_json"))
        return total, result

    def find_approved_snapshot_as_of(
        self,
        calculation_at,
        *,
        jan: str | None = None,
        location_id: str | None = None,
        location_type: str | None = None,
    ) -> dict | None:
        clauses = ["s.known_at<=?", "s.snapshot_at<=?", "d.decision='APPROVED'"]
        timestamp = canonical_datetime(calculation_at, "calculation_at")
        params: list[object] = [timestamp, timestamp, timestamp]
        filters: list[str] = []
        for column, value in (
            ("b.jan", jan),
            ("b.location_id", location_id),
            ("l.location_type", location_type),
        ):
            if value is not None:
                filters.append(f"{column}=?")
                params.append(value)
        if filters:
            clauses.append(
                "EXISTS (SELECT 1 FROM inventory_expiry_buckets b "
                "JOIN inventory_locations l ON l.location_master_version=b.location_master_version "
                "AND l.location_id=b.location_id WHERE b.snapshot_id=s.snapshot_id AND "
                + " AND ".join(filters)
                + ")"
            )
        with self._connect() as db:
            row = db.execute(
                "SELECT s.snapshot_id,s.job_id,s.snapshot_at,s.known_at,s.source_kind,"
                "s.mapping_version,s.location_master_version,s.product_mapping_version,"
                "s.normalized_unit,s.row_count,s.quantity_cases_total,s.content_sha256,"
                "s.created_at,d.revision AS decision_revision,d.decided_at "
                "FROM inventory_snapshots s JOIN inventory_snapshot_decisions d "
                "ON d.snapshot_id=s.snapshot_id AND d.decided_at<=? "
                "AND d.revision=(SELECT MAX(d2.revision) FROM inventory_snapshot_decisions d2 "
                "WHERE d2.snapshot_id=s.snapshot_id AND d2.decided_at<=?) WHERE "
                + " AND ".join(clauses)
                + " ORDER BY s.snapshot_at DESC,s.known_at DESC,s.snapshot_id DESC LIMIT 1",
                (timestamp, *params),
            ).fetchone()
        return None if row is None else dict(row)
