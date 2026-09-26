"""Phase 3S-8: 確認済みJAN対応表の正式mapping台帳。"""

import json
from datetime import UTC, datetime

import pytest

from forecast_provider.inventory_foundation import (
    ProductMappingRecord,
    SqliteInventoryFoundationStore,
    parse_confirmed_product_mapping_csv,
)
from forecast_provider.product_mapping_import import main

NOW = datetime(2026, 9, 26, 1, 2, 3, tzinfo=UTC)
VALID_JAN = "4901234567894"
OTHER_JAN = "4901234567887"


def _csv(*rows: str) -> bytes:
    text = "商品コード,商品名,JAN,確認メモ\r\n" + "\r\n".join(rows) + "\r\n"
    return ("\ufeff" + text).encode("utf-8")


def _parse(content: bytes, **overrides):
    arguments = {
        "source_reference": "product-jan-source-sha256",
        "created_by": "operator-1",
        "reason": "担当者確認済み対応表",
        "created_at": NOW,
    }
    arguments.update(overrides)
    return parse_confirmed_product_mapping_csv(content, **arguments)


def test_confirmed_csv_builds_deterministic_version_without_inventing_canonical_id():
    first = _parse(
        _csv(
            f"P-002,商品B,{OTHER_JAN},確認済み",
            f"P-001,商品A,{VALID_JAN},確認済み",
        )
    )
    second = _parse(
        _csv(
            f"P-001,名称変更後,{VALID_JAN},確認済み",
            f"P-002,商品B,{OTHER_JAN},確認済み",
        )
    )

    assert first.version.product_mapping_version == second.version.product_mapping_version
    assert first.version.content_sha256 == second.version.content_sha256
    assert [record.source_product_code for record in first.records] == ["P-001", "P-002"]
    assert all(record.canonical_product_id is None for record in first.records)


def test_existing_canonical_product_links_can_be_reused():
    imported = _parse(
        _csv(f"P-001,商品A,{VALID_JAN},確認済み"),
        jan_canonical_ids={VALID_JAN: "canonical-1"},
    )

    assert imported.records[0].canonical_product_id == "canonical-1"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (_csv(f"P-001,商品A,{VALID_JAN},要確認"), "全行の確認メモ"),
        (_csv("P-001,商品A,,確認済み"), "商品コードとJAN"),
        (_csv("P-001,商品A,123,確認済み"), "JAN"),
        (
            _csv(
                f"P-001,商品A,{VALID_JAN},確認済み",
                f"P-001,商品A,{VALID_JAN},確認済み",
            ),
            "重複",
        ),
    ],
)
def test_unapproved_or_invalid_csv_is_rejected(content, message):
    with pytest.raises(ValueError, match=message):
        _parse(content)


def test_store_persists_version_and_records_as_immutable_ledger(tmp_path):
    imported = _parse(
        _csv(f"P-001,商品A,{VALID_JAN},確認済み"),
        jan_canonical_ids={VALID_JAN: "canonical-1"},
    )
    store = SqliteInventoryFoundationStore(tmp_path / "inventory.sqlite3")

    store.put_product_mapping(imported.version, imported.records)

    assert store.get_product_mapping_version(
        imported.version.product_mapping_version
    ) == imported.version
    assert store.list_product_mappings(imported.version.product_mapping_version) == imported.records
    store.put_product_mapping(imported.version, imported.records)
    assert store.list_product_mappings(imported.version.product_mapping_version) == imported.records
    changed = (
        ProductMappingRecord(
            imported.version.product_mapping_version,
            "P-001",
            OTHER_JAN,
            "canonical-1",
        ),
    )
    with pytest.raises(ValueError, match="内容は変更できません"):
        store.put_product_mapping(imported.version, changed)


def test_cli_registers_mapping_without_printing_business_values(tmp_path, capsys):
    source = tmp_path / "confirmed.csv"
    source.write_bytes(_csv(f"P-001,商品A,{VALID_JAN},確認済み"))
    database = tmp_path / "inventory.sqlite3"

    assert main(
        [
            "--sqlite",
            str(database),
            "--csv",
            str(source),
            "--created-by",
            "operator-1",
            "--reason",
            "商品マスター照合済み",
        ]
    ) == 0

    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["row_count"] == 1
    assert result["canonical_product_linked_count"] == 0
    assert "P-001" not in output
    assert VALID_JAN not in output
