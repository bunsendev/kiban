"""Phase 3S-10: 確認済みInventory Input Mappingの正式取込。"""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from forecast_provider.inventory_foundation import (
    SqliteInventoryFoundationStore,
    parse_confirmed_input_mapping_csv,
    parse_confirmed_location_master_csv,
    parse_confirmed_product_mapping_csv,
)
from forecast_provider.inventory_input_mapping_import import main

NOW = datetime(2026, 9, 26, 3, 4, 5, tzinfo=UTC)
VALID_JAN = "4901234567894"
HEADER = (
    "商品列,商品識別種別,商品mapping版,拠点列,location master版,賞味期限列,"
    "数量列,snapshot日時列,原本数量列名,原本単位表記,正規化単位,文字コード,"
    "区切り文字,header行,確認メモ\r\n"
)


def _csv(row: str) -> bytes:
    return ("\ufeff" + HEADER + row + "\r\n").encode("utf-8")


def _row(base_product_version: str, base_location_version: str, **overrides) -> str:
    values = {
        "product_column": "商品コード",
        "product_kind": "PRODUCT_CODE",
        "product_version": base_product_version,
        "location_column": "明細倉庫コード",
        "location_version": base_location_version,
        "expiry_column": "賞味期限",
        "quantity_column": "明細バラ数",
        "snapshot_column": "基準日時",
        "source_quantity_column": "明細バラ数",
        "source_unit": "箱",
        "normalized_unit": "CASE",
        "encoding": "cp932",
        "delimiter": "COMMA",
        "header_row": "1",
        "note": "確認済み",
    }
    values.update(overrides)
    return ",".join(values.values())


def _parse(row: str):
    return parse_confirmed_input_mapping_csv(
        _csv(row),
        created_by="operator-1",
        reason="実在庫CSV契約確認済み",
        created_at=NOW,
    )


def _references(store):
    location = parse_confirmed_location_master_csv(
        (
            "\ufeff拠点コード,拠点名,拠点種別,適用開始日,適用終了日,確認メモ\r\n"
            "W01,人工倉庫,WAREHOUSE,2026-01-01,,確認済み\r\n"
        ).encode(),
        created_by="operator-1",
        reason="fixture",
        created_at=NOW,
    )
    product = parse_confirmed_product_mapping_csv(
        (
            "\ufeff商品コード,商品名,JAN,確認メモ\r\n"
            f"P-001,人工商品,{VALID_JAN},確認済み\r\n"
        ).encode(),
        source_reference="synthetic-source",
        created_by="operator-1",
        reason="fixture",
        created_at=NOW,
    )
    store.put_location_master(location.version, location.locations)
    store.put_product_mapping(product.version, product.records)
    return product.version.product_mapping_version, location.version.location_master_version


def test_confirmed_mapping_is_deterministic_and_fixes_case_contract():
    first = _parse(_row("products-v1", "locations-v1"))
    second = _parse(_row("products-v1", "locations-v1"))

    assert first.content_sha256 == second.content_sha256
    assert first.mapping.mapping_version == second.mapping.mapping_version
    assert first.mapping.delimiter == ","
    assert first.mapping.normalized_unit.value == "CASE"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"note": "要確認"}, "確認メモ"),
        ({"product_kind": "NAME"}, "JANまたはPRODUCT_CODE"),
        ({"product_version": ""}, "product mapping version"),
        ({"normalized_unit": "EACH"}, "CASE"),
        ({"encoding": "shift_jis"}, "文字コード"),
        ({"delimiter": "SEMICOLON"}, "COMMAまたはTAB"),
        ({"header_row": "zero"}, "1以上の整数"),
    ],
)
def test_unapproved_or_invalid_mapping_is_rejected(overrides, message):
    with pytest.raises(ValueError, match=message):
        _parse(_row("products-v1", "locations-v1", **overrides))


def test_store_requires_formal_references_and_is_idempotent(tmp_path):
    store = SqliteInventoryFoundationStore(tmp_path / "inventory.sqlite3")
    missing = _parse(_row("products-v1", "locations-v1")).mapping
    with pytest.raises(ValueError, match="location master version"):
        store.put_mapping(missing)

    product_version, location_version = _references(store)
    imported = _parse(_row(product_version, location_version))
    store.put_mapping(imported.mapping)
    store.put_mapping(
        replace(
            imported.mapping,
            created_by="retry-operator",
            reason="再送",
            created_at=datetime(2026, 9, 27, tzinfo=UTC),
        )
    )

    assert store.get_mapping(imported.mapping.mapping_version) == imported.mapping
    changed = replace(imported.mapping, quantity_column="別数量列")
    with pytest.raises(ValueError, match="内容は変更できません"):
        store.put_mapping(changed)


def test_store_rejects_missing_product_mapping_reference(tmp_path):
    store = SqliteInventoryFoundationStore(tmp_path / "inventory.sqlite3")
    _, location_version = _references(store)
    missing = _parse(_row("missing-products", location_version)).mapping

    with pytest.raises(ValueError, match="product mapping version"):
        store.put_mapping(missing)


def test_cli_registers_mapping_without_printing_column_names(tmp_path, capsys):
    database = tmp_path / "inventory.sqlite3"
    store = SqliteInventoryFoundationStore(database)
    product_version, location_version = _references(store)
    source = tmp_path / "confirmed-input-mapping.csv"
    source.write_bytes(_csv(_row(product_version, location_version)))

    assert main(
        [
            "--sqlite",
            str(database),
            "--csv",
            str(source),
            "--created-by",
            "operator-1",
            "--reason",
            "実在庫CSV契約確認済み",
        ]
    ) == 0

    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["product_identifier_kind"] == "PRODUCT_CODE"
    assert result["normalized_unit"] == "CASE"
    assert "商品コード" not in output
    assert "明細倉庫コード" not in output
