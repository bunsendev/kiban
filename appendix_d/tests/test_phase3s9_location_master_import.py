"""Phase 3S-9: 確認済みlocation masterの正式取込。"""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from forecast_provider.inventory_foundation import (
    LocationType,
    SqliteInventoryFoundationStore,
    parse_confirmed_location_master_csv,
)
from forecast_provider.location_master_import import main

NOW = datetime(2026, 9, 26, 2, 3, 4, tzinfo=UTC)


def _csv(*rows: str) -> bytes:
    header = "拠点コード,拠点名,拠点種別,適用開始日,適用終了日,確認メモ\r\n"
    return ("\ufeff" + header + "\r\n".join(rows) + "\r\n").encode("utf-8")


def _parse(content: bytes):
    return parse_confirmed_location_master_csv(
        content,
        created_by="operator-1",
        reason="拠点台帳照合済み",
        created_at=NOW,
    )


def test_confirmed_csv_builds_deterministic_location_master():
    first = _parse(
        _csv(
            "W02,人工倉庫B,WAREHOUSE,2026-01-01,,確認済み",
            "F01,人工工場,FACTORY,2026-01-01,,確認済み",
            "W01,人工倉庫A,WAREHOUSE,2026-01-01,2026-12-31,確認済み",
        )
    )
    second = _parse(
        _csv(
            "W01,人工倉庫A,WAREHOUSE,2026-01-01,2026-12-31,確認済み",
            "W02,人工倉庫B,WAREHOUSE,2026-01-01,,確認済み",
            "F01,人工工場,FACTORY,2026-01-01,,確認済み",
        )
    )

    assert first.version.location_master_version == second.version.location_master_version
    assert first.version.content_sha256 == second.version.content_sha256
    assert [value.location_code for value in first.locations] == ["F01", "W01", "W02"]
    assert len({value.location_id for value in first.locations}) == 3
    assert first.locations[0].location_type is LocationType.FACTORY


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (_csv("W01,人工倉庫,WAREHOUSE,2026-01-01,,要確認"), "確認メモ"),
        (_csv("W01,,WAREHOUSE,2026-01-01,,確認済み"), "拠点コードと拠点名"),
        (_csv("W01,人工倉庫,COMPANY,2026-01-01,,確認済み"), "FACTORY"),
        (_csv("W01,人工倉庫,WAREHOUSE,2026/01/01,,確認済み"), "YYYY-MM-DD"),
        (
            _csv(
                "W01,人工倉庫A,WAREHOUSE,2026-01-01,,確認済み",
                "W01,人工倉庫B,WAREHOUSE,2026-01-01,,確認済み",
            ),
            "重複",
        ),
    ],
)
def test_unapproved_or_invalid_location_master_is_rejected(content, message):
    with pytest.raises(ValueError, match=message):
        _parse(content)


def test_store_persists_location_master_idempotently_and_rejects_mutation(tmp_path):
    imported = _parse(_csv("W01,人工倉庫,WAREHOUSE,2026-01-01,,確認済み"))
    store = SqliteInventoryFoundationStore(tmp_path / "inventory.sqlite3")

    store.put_location_master(imported.version, imported.locations)
    store.put_location_master(imported.version, imported.locations)

    assert store.get_location_master_version(
        imported.version.location_master_version
    ) == imported.version
    assert store.list_locations(imported.version.location_master_version) == imported.locations
    changed = (replace(imported.locations[0], location_name="別の倉庫"),)
    with pytest.raises(ValueError, match="内容は変更できません"):
        store.put_location_master(imported.version, changed)


def test_cli_registers_master_without_printing_location_values(tmp_path, capsys):
    source = tmp_path / "confirmed-locations.csv"
    source.write_bytes(_csv("W01,人工倉庫,WAREHOUSE,2026-01-01,,確認済み"))
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
            "拠点台帳照合済み",
        ]
    ) == 0

    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["row_count"] == 1
    assert result["factory_count"] == 0
    assert result["warehouse_count"] == 1
    assert "W01" not in output
    assert "人工倉庫" not in output
