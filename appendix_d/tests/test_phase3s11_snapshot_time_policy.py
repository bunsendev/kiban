"""Phase 3S-11: ファイル名日付を正式snapshot日時へ変換する版付きpolicy。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, time

import pytest

from forecast_provider.inventory_foundation import (
    InventoryCsvContractError,
    InventoryCsvErrorCode,
    InventoryInputMappingVersion,
    InventoryLocation,
    InventorySnapshotJobStatus,
    InventorySnapshotWorker,
    LocationMasterVersion,
    LocationType,
    NormalizedUnit,
    ProductIdentifierKind,
    SnapshotAtSourceKind,
    SqliteInventoryFoundationStore,
    build_snapshot_time_policy,
    create_inventory_snapshot_job,
    parse_confirmed_input_mapping_csv,
    parse_confirmed_snapshot_time_policy_csv,
    parse_inventory_csv,
)
from forecast_provider.snapshot_time_policy_import import main

NOW = datetime(2026, 9, 26, 3, 4, 5, tzinfo=UTC)
JAN = "4901234567894"


class MemorySourceReader:
    def __init__(self, reference: str, content: bytes):
        self.reference = reference
        self.content = content

    def read(self, source_reference: str) -> bytes:
        assert source_reference == self.reference
        return self.content


def _policy():
    return build_snapshot_time_policy(
        cutoff_time=time(9),
        timezone_name="Asia/Tokyo",
        created_by="operator-1",
        reason="人工fixture",
        created_at=NOW,
    )


def _mapping(policy_version: str) -> InventoryInputMappingVersion:
    return InventoryInputMappingVersion(
        "inventory-map-filename-v1",
        "JAN",
        ProductIdentifierKind.JAN,
        None,
        "拠点",
        "locations-v1",
        "賞味期限",
        "明細バラ数",
        "__snapshot_at__",
        "明細バラ数",
        "箱",
        NormalizedUnit.CASE,
        "utf-8-sig",
        ",",
        1,
        "tester",
        "fixture",
        NOW,
        SnapshotAtSourceKind.FILENAME_YYYYMMDD,
        policy_version,
    )


def _content() -> bytes:
    return (
        "JAN,拠点,賞味期限,明細バラ数\n"
        f"{JAN},W01,2026-12-31,3\n"
    ).encode("utf-8-sig")


def test_policy_is_deterministic_and_resolves_explicit_jst_cutoff():
    first = _policy()
    second = _policy()
    assert first.policy_version == second.policy_version
    assert first.resolve("archive/inventory_20260924.csv") == datetime(
        2026, 9, 24, 0, 0, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "reference",
    ["inventory.csv", "inventory_20260230.csv", "inventory_20260924.csv.bak"],
)
def test_invalid_filename_is_a_fixed_contract_error(reference):
    policy = _policy()
    with pytest.raises(InventoryCsvContractError) as raised:
        parse_inventory_csv(
            _content(),
            _mapping(policy.policy_version),
            source_reference=reference,
            snapshot_time_policy=policy,
        )
    assert raised.value.code is InventoryCsvErrorCode.SNAPSHOT_FILENAME_INVALID
    assert reference not in str(raised.value)


def test_column_mode_remains_compatible():
    mapping = replace(
        _mapping(_policy().policy_version),
        snapshot_at_source_kind=SnapshotAtSourceKind.COLUMN,
        snapshot_at_policy_version=None,
        snapshot_at_column="基準日時",
    )
    content = (
        "JAN,拠点,賞味期限,明細バラ数,基準日時\n"
        f"{JAN},W01,2026-12-31,3,2026-09-24T08:00:00+00:00\n"
    ).encode("utf-8-sig")
    parsed = parse_inventory_csv(content, mapping)
    assert parsed.rows[0].as_dict()["基準日時"] == "2026-09-24T08:00:00+00:00"


def test_worker_accepts_csv_without_snapshot_column_using_filename_policy(tmp_path):
    store = SqliteInventoryFoundationStore(tmp_path / "inventory.sqlite3")
    policy = _policy()
    mapping = _mapping(policy.policy_version)
    location_version = LocationMasterVersion("locations-v1", "a" * 64, "test", "fixture", NOW)
    store.put_location_master(
        location_version,
        (
            InventoryLocation(
                "locations-v1",
                "warehouse-1",
                "W01",
                "人工倉庫",
                LocationType.WAREHOUSE,
                date(2026, 1, 1),
            ),
        ),
    )
    with pytest.raises(ValueError, match="snapshot time policy version"):
        store.put_mapping(mapping)
    store.put_snapshot_time_policy(policy)
    store.put_mapping(mapping)
    content = _content()
    reference = "incoming/inventory_20260924.csv"
    job = create_inventory_snapshot_job(
        source_reference=reference,
        source_sha256=hashlib.sha256(content).hexdigest(),
        mapping_version=mapping.mapping_version,
        requested_by="tester",
        known_at=NOW,
        requested_at=NOW,
    )
    store.put_job(job)
    completed = InventorySnapshotWorker(
        store,
        MemorySourceReader(reference, content),
        clock=lambda: NOW,
    ).run_once("worker-1")
    assert completed.status is InventorySnapshotJobStatus.SUCCEEDED
    snapshot = store.list_snapshots(job.job_id)[0]
    assert datetime.fromisoformat(snapshot["snapshot_at"].replace("Z", "+00:00")) == datetime(
        2026, 9, 24, tzinfo=UTC
    )


def test_confirmed_csv_contracts_and_cli_do_not_output_source_names(tmp_path, capsys):
    policy_csv = (
        "\ufeff日付取得方式,締め時刻,timezone,確認メモ\r\n"
        "FILENAME_YYYYMMDD,09:00:00,Asia/Tokyo,確認済み\r\n"
    ).encode()
    policy = parse_confirmed_snapshot_time_policy_csv(
        policy_csv, created_by="operator", reason="確認済み", created_at=NOW
    )
    extended_mapping = (
        "\ufeff商品列,商品識別種別,商品mapping版,拠点列,location master版,賞味期限列,"
        "数量列,snapshot日時列,原本数量列名,原本単位表記,正規化単位,文字コード,"
        "区切り文字,header行,snapshot取得方式,snapshot時刻policy版,確認メモ\r\n"
        f"JAN,JAN,,拠点,locations-v1,賞味期限,明細バラ数,__snapshot_at__,明細バラ数,"
        f"箱,CASE,utf-8-sig,COMMA,1,FILENAME_YYYYMMDD,{policy.policy_version},確認済み\r\n"
    ).encode()
    imported = parse_confirmed_input_mapping_csv(
        extended_mapping, created_by="operator", reason="確認済み", created_at=NOW
    )
    assert imported.mapping.snapshot_at_policy_version == policy.policy_version

    source = tmp_path / "policy.csv"
    source.write_bytes(policy_csv)
    database = tmp_path / "inventory.sqlite3"
    assert main(
        [
            "--sqlite",
            str(database),
            "--csv",
            str(source),
            "--created-by",
            "operator",
            "--reason",
            "確認済み",
        ]
    ) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["policy_version"] == policy.policy_version
    assert source.name not in output


def test_existing_mapping_table_is_upgraded_with_column_defaults(tmp_path):
    path = tmp_path / "upgrade.sqlite3"
    store = SqliteInventoryFoundationStore(path)
    del store
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE inventory_input_mapping_versions RENAME TO old_mappings")
        db.execute(
            "CREATE TABLE inventory_input_mapping_versions AS SELECT "
            "mapping_version,product_column,product_identifier_kind,product_mapping_version,"
            "location_column,location_master_version,expiry_column,quantity_column,"
            "snapshot_at_column,source_quantity_column_name,source_unit_label,normalized_unit,"
            "encoding,delimiter,header_row,created_by,reason,created_at FROM old_mappings"
        )
        db.execute("DROP TABLE old_mappings")
    SqliteInventoryFoundationStore(path)
    with sqlite3.connect(path) as db:
        columns = {
            row[1]
            for row in db.execute("PRAGMA table_info(inventory_input_mapping_versions)")
        }
        assert {"snapshot_at_source_kind", "snapshot_at_policy_version"}.issubset(columns)
