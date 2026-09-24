"""Phase 3S-2: versioned CSV adapter、validation、quarantine。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from forecast_provider.inventory_foundation import (
    InventoryCsvContractError,
    InventoryCsvErrorCode,
    InventoryInputMappingVersion,
    InventoryLocation,
    InventoryReferenceResolver,
    LocationType,
    NormalizedUnit,
    ProductIdentifierKind,
    ProductMappingRecord,
    QuarantineReason,
    parse_inventory_csv,
    validate_inventory_csv,
)

NOW = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
VALID_JAN = "4901234567894"
OTHER_JAN = "4901234560017"


def _mapping(**changes) -> InventoryInputMappingVersion:
    base = InventoryInputMappingVersion(
        mapping_version="inventory-map-v1",
        product_column="JAN",
        product_identifier_kind=ProductIdentifierKind.JAN,
        product_mapping_version=None,
        location_column="拠点",
        location_master_version="locations-v1",
        expiry_column="賞味期限",
        quantity_column="明細バラ数",
        snapshot_at_column="基準日時",
        source_quantity_column_name="明細バラ数",
        source_unit_label="箱",
        normalized_unit=NormalizedUnit.CASE,
        encoding="utf-8-sig",
        delimiter=",",
        header_row=1,
        created_by="tester",
        reason="fixture",
        created_at=NOW,
    )
    return replace(base, **changes)


def _locations() -> tuple[InventoryLocation, ...]:
    return (
        InventoryLocation(
            "locations-v1",
            "factory-1",
            "F01",
            "人工工場",
            LocationType.FACTORY,
            date(2026, 1, 1),
        ),
        InventoryLocation(
            "locations-v1",
            "warehouse-1",
            "W01",
            "人工倉庫",
            LocationType.WAREHOUSE,
            date(2026, 1, 1),
        ),
    )


def _run(text: str, *, mapping=None, locations=None, product_mappings=()):
    mapping = mapping or _mapping()
    content = text.encode(mapping.encoding)
    parsed = parse_inventory_csv(content, mapping)
    resolver = InventoryReferenceResolver(
        mapping,
        locations or _locations(),
        product_mappings,
        {VALID_JAN: "canonical-1"},
    )
    return parsed, validate_inventory_csv(parsed, mapping, resolver)


def _csv(*rows: str) -> str:
    return "JAN,拠点,賞味期限,明細バラ数,基準日時\n" + "\n".join(rows) + "\n"


def test_csv_normalizes_factory_and_warehouse_and_aggregates_buckets():
    _, result = _run(
        _csv(
            f"{VALID_JAN},F01,2026/12/31,1.00,2026-09-24T17:00:00+09:00",
            f"{VALID_JAN},W01,2026-12-31,2,2026-09-24T08:00:00Z",
            f"{VALID_JAN},W01,2026-12-31 12:00:00,3,2026-09-24T08:00:00Z",
        )
    )
    assert result.approval_ready
    assert result.snapshot_at == NOW
    assert [(item.location_id, item.quantity_cases) for item in result.buckets] == [
        ("factory-1", Decimal("1.00")),
        ("warehouse-1", Decimal("5")),
    ]
    assert all(item.normalized_unit is NormalizedUnit.CASE for item in result.buckets)
    assert result.reconciliation.source_quantity_cases == Decimal("6.00")
    assert result.reconciliation.normalized_quantity_cases == Decimal("6.00")


def test_cp932_custom_delimiter_and_header_row_are_mapping_controlled():
    mapping = _mapping(encoding="cp932", delimiter=";", header_row=2)
    text = (
        "取込説明;;;;\n"
        "JAN;拠点;賞味期限;明細バラ数;基準日時\n"
        f"{VALID_JAN};W01;2026/12/31;1,200;2026-09-24T08:00:00Z\n"
    )
    _, result = _run(text, mapping=mapping)
    assert result.approval_ready
    assert result.buckets[0].quantity_cases == Decimal("1200")


def test_product_code_resolves_with_fixed_mapping_version():
    mapping = _mapping(
        product_column="商品コード",
        product_identifier_kind=ProductIdentifierKind.PRODUCT_CODE,
        product_mapping_version="products-v7",
    )
    products = (
        ProductMappingRecord("products-v7", "P-001", VALID_JAN, "canonical-1"),
        ProductMappingRecord("products-v6", "P-001", OTHER_JAN, "old-canonical"),
    )
    text = (
        "商品コード,拠点,賞味期限,明細バラ数,基準日時\n"
        "P-001,W01,2026-12-31,4,2026-09-24T08:00:00Z\n"
    )
    _, result = _run(text, mapping=mapping, product_mappings=products)
    assert result.approval_ready
    assert result.buckets[0].jan == VALID_JAN
    assert result.buckets[0].canonical_product_id == "canonical-1"


@pytest.mark.parametrize(
    ("product_mappings", "expected"),
    [
        ((), QuarantineReason.PRODUCT_MAPPING_MISSING),
        (
            (
                ProductMappingRecord("products-v7", "P-001", VALID_JAN, "canonical-1"),
                ProductMappingRecord("products-v7", "P-001", OTHER_JAN, "canonical-2"),
            ),
            QuarantineReason.PRODUCT_MAPPING_AMBIGUOUS,
        ),
    ],
)
def test_product_mapping_missing_or_ambiguous_is_quarantined(product_mappings, expected):
    mapping = _mapping(
        product_column="商品コード",
        product_identifier_kind=ProductIdentifierKind.PRODUCT_CODE,
        product_mapping_version="products-v7",
    )
    text = (
        "商品コード,拠点,賞味期限,明細バラ数,基準日時\n"
        "P-001,W01,2026-12-31,4,2026-09-24T08:00:00Z\n"
    )
    _, result = _run(text, mapping=mapping, product_mappings=product_mappings)
    assert not result.approval_ready
    assert result.quarantines[0].reasons == (expected,)
    assert result.reconciliation.source_quantity_cases == Decimal("4")
    assert result.reconciliation.normalized_quantity_cases == Decimal("0")


def test_invalid_rows_return_only_metadata_and_fixed_reason_codes():
    secret = "外部へ表示してはいけない値"
    parsed, result = _run(
        _csv(
            f"BAD,W99,,{secret},2026-09-24 08:00:00",
            f"{VALID_JAN},W01,2026-12-31,-1,2026-09-24T08:00:00Z",
        )
    )
    first_reasons = set(result.quarantines[0].reasons)
    assert first_reasons == {
        QuarantineReason.EXPIRY_MISSING,
        QuarantineReason.JAN_INVALID,
        QuarantineReason.LOCATION_UNKNOWN,
        QuarantineReason.QUANTITY_INVALID,
        QuarantineReason.SNAPSHOT_AT_INVALID,
    }
    assert result.quarantines[1].reasons == (QuarantineReason.QUANTITY_NEGATIVE,)
    assert secret not in repr(parsed.rows[0])
    assert secret not in repr(result)


def test_duplicate_row_is_quarantined_and_quantity_reconciliation_detects_loss():
    row = f"{VALID_JAN},W01,2026-12-31,7,2026-09-24T08:00:00Z"
    _, result = _run(_csv(row, row))
    assert result.quarantines[0].row_number == 3
    assert result.quarantines[0].reasons == (QuarantineReason.SOURCE_DUPLICATE,)
    assert result.buckets[0].quantity_cases == Decimal("7")
    assert result.reconciliation.source_quantity_cases == Decimal("14")
    assert not result.reconciliation.reconciled
    assert not result.approval_ready


def test_different_snapshot_times_quarantine_all_otherwise_valid_rows():
    _, result = _run(
        _csv(
            f"{VALID_JAN},W01,2026-12-31,1,2026-09-24T08:00:00Z",
            f"{VALID_JAN},F01,2026-12-31,1,2026-09-24T09:00:00Z",
        )
    )
    assert result.snapshot_at is None
    assert not result.buckets
    assert all(
        row.reasons == (QuarantineReason.SNAPSHOT_AT_INCONSISTENT,)
        for row in result.quarantines
    )


def test_row_shape_error_is_quarantined_without_copying_values():
    _, result = _run(
        _csv(f"{VALID_JAN},W01,2026-12-31,2,2026-09-24T08:00:00Z,EXTRA")
    )
    assert result.quarantines[0].reasons == (QuarantineReason.ROW_SHAPE_INVALID,)
    assert result.reconciliation.source_quantity_cases == Decimal("0")


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"", InventoryCsvErrorCode.EMPTY_SOURCE),
        (b"JAN,missing\n1,2\n", InventoryCsvErrorCode.REQUIRED_COLUMN_MISSING),
        (b"\xff", InventoryCsvErrorCode.DECODE_FAILED),
    ],
)
def test_csv_contract_errors_expose_only_fixed_code(content, expected):
    with pytest.raises(InventoryCsvContractError) as captured:
        parse_inventory_csv(content, _mapping())
    assert captured.value.code is expected
    assert str(captured.value) == expected.value


def test_mapping_encoding_allowlist_rejects_unexpected_codec():
    with pytest.raises(InventoryCsvContractError) as captured:
        parse_inventory_csv(_csv().encode("utf-16"), _mapping(encoding="utf-16"))
    assert captured.value.code is InventoryCsvErrorCode.ENCODING_UNSUPPORTED


def test_inactive_location_is_not_accepted_for_snapshot_date():
    expired = replace(_locations()[1], effective_to=date(2026, 9, 23))
    _, result = _run(
        _csv(f"{VALID_JAN},W01,2026-12-31,1,2026-09-24T08:00:00Z"),
        locations=(_locations()[0], expired),
    )
    assert result.quarantines[0].reasons == (QuarantineReason.LOCATION_UNKNOWN,)


def test_parser_validator_and_resolver_must_share_mapping_contract():
    original = _mapping()
    parsed = parse_inventory_csv(
        _csv(f"{VALID_JAN},W01,2026-12-31,1,2026-09-24T08:00:00Z").encode(
            original.encoding
        ),
        original,
    )
    changed = replace(original, mapping_version="inventory-map-v2")
    resolver = InventoryReferenceResolver(changed, _locations())
    with pytest.raises(ValueError, match="mapping contract"):
        validate_inventory_csv(parsed, changed, resolver)
