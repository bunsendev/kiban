"""Phase 3S-1: inventory foundation domain/schema。"""

from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from forecast_provider.inventory_foundation import (
    ExtractionReviewDecision,
    ExtractionStatus,
    InventoryExpiryBucket,
    InventoryExtraction,
    InventoryExtractionReview,
    InventoryInputMappingVersion,
    InventoryIssueCode,
    InventoryLocation,
    InventorySourceDocument,
    LocationMasterVersion,
    LocationType,
    NormalizedUnit,
    PostgresInventoryFoundationStore,
    ProductIdentifierKind,
    RecommendationBasis,
    RouteLeadTimePolicy,
    SourceKind,
    SqliteInventoryFoundationStore,
    build_inventory_snapshot,
    canonical_decimal,
    validate_jan,
    validate_route_locations,
    verify_snapshot_identity,
)
from forecast_provider.inventory_normalization import SqliteInventoryNormalizationStore

NOW = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
VALID_JAN = "4901234567894"


def _master(suffix: str = "1"):
    version_id = f"locations-v{suffix}"
    version = LocationMasterVersion(version_id, SHA_A, "tester", "fixture", NOW)
    locations = (
        InventoryLocation(
            version_id,
            f"factory-{suffix}",
            f"F{suffix}",
            "人工工場",
            LocationType.FACTORY,
            date(2026, 1, 1),
        ),
        InventoryLocation(
            version_id,
            f"warehouse-{suffix}",
            f"W{suffix}",
            "人工倉庫",
            LocationType.WAREHOUSE,
            date(2026, 1, 1),
        ),
    )
    return version, locations


def _mapping(version: LocationMasterVersion, suffix: str = "1"):
    return InventoryInputMappingVersion(
        mapping_version=f"inventory-map-v{suffix}",
        product_column="JAN",
        product_identifier_kind=ProductIdentifierKind.JAN,
        product_mapping_version=None,
        location_column="location_code",
        location_master_version=version.location_master_version,
        expiry_column="expiry_date",
        quantity_column="明細バラ数",
        snapshot_at_column="snapshot_at",
        source_quantity_column_name="明細バラ数",
        source_unit_label="箱",
        normalized_unit=NormalizedUnit.CASE,
        encoding="cp932",
        delimiter=",",
        header_row=1,
        created_by="tester",
        reason="fixture",
        created_at=NOW,
    )


def _bucket(
    location_id: str = "warehouse-1",
    expiry: date = date(2026, 12, 31),
    quantity: Decimal = Decimal("1.00"),
):
    return InventoryExpiryBucket(
        jan=VALID_JAN,
        canonical_product_id="product-1",
        location_id=location_id,
        expiry_date=expiry,
        quantity_cases=quantity,
    )


def _snapshot(
    buckets,
    *,
    source_kind=SourceKind.CSV,
    source_reference="source.csv",
    pdf_approval=None,
):
    return build_inventory_snapshot(
        snapshot_at=NOW,
        known_at=NOW + timedelta(hours=1),
        source_kind=source_kind,
        source_reference=source_reference,
        source_sha256=SHA_B,
        mapping_version="inventory-map-v1",
        location_master_version="locations-v1",
        product_mapping_version="JAN-DIRECT-v1",
        buckets=buckets,
        created_at=NOW + timedelta(hours=2),
        pdf_approval=pdf_approval,
    )


def _prepare_store(path: Path):
    store = SqliteInventoryFoundationStore(path)
    version, locations = _master()
    store.put_location_master(version, locations)
    store.put_mapping(_mapping(version))
    return store, version, locations


def test_location_type_accepts_only_factory_and_warehouse():
    assert LocationType("FACTORY") is LocationType.FACTORY
    assert LocationType("WAREHOUSE") is LocationType.WAREHOUSE
    with pytest.raises(ValueError):
        LocationType("COMPANY")


@pytest.mark.parametrize(
    ("minimum", "standard", "maximum"),
    [(11, 12, 13), (12, 11, 13), (12, 14, 13), (12, 13, 37)],
)
def test_route_lead_time_v1_boundary(minimum, standard, maximum):
    with pytest.raises(ValueError, match="12 <= minimum"):
        RouteLeadTimePolicy(
            "policy-1",
            "route-v1",
            "locations-v1",
            "factory-1",
            "warehouse-1",
            minimum,
            standard,
            maximum,
            RecommendationBasis.STANDARD,
            date(2026, 1, 1),
        )


def test_route_selects_versioned_recommendation_basis_and_location_types():
    _, locations = _master()
    policy = RouteLeadTimePolicy(
        "policy-1",
        "route-v1",
        "locations-v1",
        "factory-1",
        "warehouse-1",
        12,
        24,
        36,
        RecommendationBasis.MAXIMUM,
        date(2026, 1, 1),
    )
    validate_route_locations(policy, locations)
    assert policy.selected_lead_time_hours == 36
    with pytest.raises(ValueError, match="factory_location_id"):
        validate_route_locations(
            replace(
                policy,
                factory_location_id="warehouse-1",
                warehouse_location_id="factory-1",
            ),
            locations,
        )
    with pytest.raises(ValueError, match="recommendation_basis"):
        replace(policy, recommendation_basis="AVERAGE")


def test_jan_and_expiry_bucket_validation():
    assert validate_jan(VALID_JAN) == VALID_JAN
    for invalid in ("", "4901234567890", "ABCDEFGHIJKLM", "123"):
        with pytest.raises(ValueError):
            validate_jan(invalid)
    with pytest.raises(ValueError, match="expiry_date"):
        InventoryExpiryBucket(VALID_JAN, None, "warehouse-1", NOW, Decimal("1"))
    with pytest.raises(ValueError, match="0以上"):
        _bucket(quantity=Decimal("-1"))
    with pytest.raises(ValueError, match="binary float"):
        _bucket(quantity=1.0)


def test_mapping_requires_case_and_explicit_product_mapping_contract():
    version, _ = _master()
    mapping = _mapping(version)
    assert mapping.source_quantity_column_name == "明細バラ数"
    assert mapping.source_unit_label == "箱"
    assert mapping.normalized_unit is NormalizedUnit.CASE
    with pytest.raises(ValueError):
        NormalizedUnit("EACH")
    with pytest.raises(ValueError, match="product mapping version"):
        replace(
            mapping,
            product_identifier_kind=ProductIdentifierKind.PRODUCT_CODE,
            product_mapping_version=None,
        )


def test_snapshot_rejects_timezone_naive_business_times():
    with pytest.raises(ValueError, match="timezone"):
        build_inventory_snapshot(
            snapshot_at=datetime(2026, 9, 24, 8, 0),
            known_at=NOW,
            source_kind=SourceKind.CSV,
            source_reference="source.csv",
            source_sha256=SHA_B,
            mapping_version="inventory-map-v1",
            location_master_version="locations-v1",
            product_mapping_version="JAN-DIRECT-v1",
            buckets=[_bucket()],
            created_at=NOW,
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1"), "1"),
        (Decimal("1.0"), "1"),
        (Decimal("1.00"), "1"),
        (Decimal("0.000"), "0"),
        (Decimal("12.3400"), "12.34"),
    ],
)
def test_decimal_canonicalization(value, expected):
    assert canonical_decimal(value) == expected


def test_snapshot_identity_is_deterministic_and_order_independent():
    first = _bucket(quantity=Decimal("1.0"))
    second = InventoryExpiryBucket(
        VALID_JAN,
        "product-1",
        "factory-1",
        date(2027, 1, 31),
        Decimal("2.00"),
    )
    left = _snapshot([first, second])
    right = _snapshot([replace(second, quantity_cases=Decimal("2")), first])
    assert left.header.snapshot_id == right.header.snapshot_id
    assert left.header.content_sha256 == right.header.content_sha256
    assert left.header.quantity_cases_total == Decimal("3.0")
    verify_snapshot_identity(left)


def test_snapshot_identity_changes_for_known_at_but_not_created_at():
    original = _snapshot([_bucket()])
    changed_created = build_inventory_snapshot(
        snapshot_at=NOW,
        known_at=NOW + timedelta(hours=1),
        source_kind=SourceKind.CSV,
        source_reference="source.csv",
        source_sha256=SHA_B,
        mapping_version="inventory-map-v1",
        location_master_version="locations-v1",
        product_mapping_version="JAN-DIRECT-v1",
        buckets=[_bucket()],
        created_at=NOW + timedelta(days=1),
    )
    changed_known = replace(original.header, known_at=NOW + timedelta(hours=2))
    assert original.header.snapshot_id == changed_created.header.snapshot_id
    with pytest.raises(ValueError, match="identity"):
        verify_snapshot_identity(replace(original, header=changed_known))


def test_expired_bucket_is_preserved_with_fixed_issue_code(tmp_path):
    store, _, _ = _prepare_store(tmp_path / "expired.sqlite3")
    snapshot = _snapshot([_bucket(expiry=date(2026, 9, 1), quantity=Decimal("4"))])
    assert snapshot.buckets[0].issue_codes == (InventoryIssueCode.EXPIRED_AT_SNAPSHOT,)
    store.put_snapshot(snapshot)
    assert store.list_expiry_buckets(snapshot.header.snapshot_id) == [
        {
            "jan": VALID_JAN,
            "canonical_product_id": "product-1",
            "location_id": "warehouse-1",
            "expiry_date": "2026-09-01",
            "bucket_kind": "EXPIRY_BUCKET",
            "quantity_cases": "4",
            "normalized_unit": "CASE",
            "issue_codes": ["EXPIRED_AT_SNAPSHOT"],
        }
    ]


def test_sqlite_additive_migration_keeps_existing_inventory_schema(tmp_path):
    path = tmp_path / "existing.sqlite3"
    SqliteInventoryNormalizationStore(path)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE existing_marker(value TEXT NOT NULL)")
        db.execute("INSERT INTO existing_marker VALUES ('kept')")
    SqliteInventoryFoundationStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM existing_marker").fetchone()[0] == "kept"
        names = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "inventory_daily_quantities" in names
    assert "inventory_snapshots" in names
    assert "inventory_expiry_buckets" in names


def test_schema_contains_all_phase3s1_tables_and_cross_database_constraints():
    sql = (
        Path(__file__).parents[1]
        / "forecast_provider"
        / "inventory_foundation"
        / "schema.sql"
    ).read_text(encoding="utf-8")
    expected = {
        "inventory_location_master_versions",
        "inventory_locations",
        "inventory_route_lead_time_policies",
        "inventory_input_mapping_versions",
        "inventory_snapshot_jobs",
        "inventory_snapshots",
        "inventory_expiry_buckets",
        "inventory_snapshot_quarantines",
        "inventory_snapshot_reconciliations",
        "inventory_snapshot_decisions",
        "inventory_source_documents",
        "inventory_extractions",
        "inventory_extraction_reviews",
    }
    assert all(f"CREATE TABLE IF NOT EXISTS {name}" in sql for name in expected)
    assert "CHECK(12 <= minimum_hours)" in sql
    assert "CHECK(normalized_unit='CASE')" in sql
    assert "pdf_review_decision='APPROVED'" in sql
    assert "REFERENCES inventory_extraction_reviews" in sql
    assert "TIMESTAMPTZ" in sql
    assert "pg_advisory_xact_lock" in (
        Path(__file__).parents[1]
        / "forecast_provider"
        / "inventory_foundation"
        / "postgres.py"
    ).read_text(encoding="utf-8")


def test_pdf_extraction_requires_human_approval_before_snapshot(tmp_path):
    store, _, _ = _prepare_store(tmp_path / "pdf.sqlite3")
    document = InventorySourceDocument("doc-1", "application/pdf", "archive/doc-1", SHA_A, NOW)
    extraction = InventoryExtraction(
        "extraction-1",
        document.document_id,
        "fixture-extractor",
        "1",
        SHA_A,
        "structured/extraction-1.json",
        SHA_B,
        ExtractionStatus.REVIEW_REQUIRED,
        NOW,
    )
    store.put_source_document(document)
    store.put_extraction(extraction)
    with pytest.raises(ValueError, match="未承認PDF"):
        _snapshot(
            [_bucket()],
            source_kind=SourceKind.PDF_EXTRACTED,
            source_reference=extraction.extraction_id,
        )
    rejected = InventoryExtractionReview(
        "review-rejected",
        extraction.extraction_id,
        ExtractionReviewDecision.REJECTED,
        "reviewer",
        "人工fixtureで不採用",
        NOW,
    )
    store.put_extraction_review(rejected)
    with pytest.raises(ValueError, match="承認済み"):
        rejected.approval_reference()
    approved = InventoryExtractionReview(
        "review-approved",
        extraction.extraction_id,
        ExtractionReviewDecision.APPROVED,
        "reviewer",
        "人工fixtureで確認済み",
        NOW + timedelta(minutes=1),
    )
    store.put_extraction_review(approved)
    snapshot = _snapshot(
        [_bucket()],
        source_kind=SourceKind.PDF_EXTRACTED,
        source_reference=extraction.extraction_id,
        pdf_approval=approved.approval_reference(),
    )
    store.put_snapshot(snapshot)
    assert len(store.list_expiry_buckets(snapshot.header.snapshot_id)) == 1


def test_store_rejects_route_when_location_roles_are_reversed(tmp_path):
    store, version, _ = _prepare_store(tmp_path / "route.sqlite3")
    invalid = RouteLeadTimePolicy(
        "policy-1",
        "route-v1",
        version.location_master_version,
        "warehouse-1",
        "factory-1",
        12,
        24,
        36,
        RecommendationBasis.STANDARD,
        date(2026, 1, 1),
    )
    with pytest.raises(ValueError, match="factory_location_id"):
        store.put_route_policy(invalid)


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL DSN未設定")
def test_postgres_inventory_foundation_matches_sqlite_contract():
    suffix = uuid.uuid4().hex
    store = PostgresInventoryFoundationStore(os.environ["KIBAN_TEST_POSTGRES_DSN"])
    version, locations = _master(suffix)
    store.put_location_master(version, locations)
    mapping = _mapping(version, suffix)
    store.put_mapping(mapping)
    snapshot = build_inventory_snapshot(
        snapshot_at=NOW,
        known_at=NOW + timedelta(hours=1),
        source_kind=SourceKind.CSV,
        source_reference=f"source-{suffix}.csv",
        source_sha256=SHA_B,
        mapping_version=mapping.mapping_version,
        location_master_version=version.location_master_version,
        product_mapping_version="JAN-DIRECT-v1",
        buckets=[_bucket(location_id=locations[1].location_id)],
        created_at=NOW,
    )
    store.put_snapshot(snapshot)
    rows = store.list_expiry_buckets(snapshot.header.snapshot_id)
    assert rows[0]["quantity_cases"] == "1"
    assert rows[0]["normalized_unit"] == "CASE"
