"""確認済みJANの部分採用と出荷履歴との矛盾隔離。"""

from datetime import UTC, date, datetime

import pytest

from forecast_provider.field_pilot.formal_product_mapping import (
    publish_confirmed_product_mapping,
)
from forecast_provider.field_pilot.local_setting_store import LocalSettingStore
from forecast_provider.inventory_foundation.store import SqliteInventoryFoundationStore


class MappingStore:
    def __init__(self):
        self.saved = []

    def put_product_mapping(self, version, records):
        self.saved.append((version, records))


def _confirmed(store, code, jan):
    store.append(
        change_type="JAN_MAPPING", target=code,
        value={"jan": jan, "product_name": f"name-{code}"},
        effective_from=date(2026, 9, 1), actor="manager",
        reason_code="INITIAL_CONFIRMATION", comment="", application_version="test",
        expected_version=None, changed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def test_publication_uses_confirmed_subset_and_holds_jan_conflict(tmp_path):
    archive = tmp_path / "Inbox" / "Archive" / "ab" / "abcdef"
    archive.mkdir(parents=True)
    (archive / "stock.csv").write_bytes((
        "商品コード,商品名,明細倉庫コード,明細バラ数\n"
        "A1,商品A,EAST,4\nB2,商品B,EAST,5\nC3,商品C,EAST,6\n"
    ).encode("cp932"))
    (archive / "shipment.csv").write_bytes((
        "出荷日,商品コード,商品名,JAN,数量\n"
        "2026-09-01,A1,商品A,4901234567894,3\n"
        "2026-09-01,B2,商品B,4901234567894,3\n"
    ).encode("cp932"))
    settings = LocalSettingStore(tmp_path / "settings.sqlite3")
    _confirmed(settings, "A1", "4901234567894")
    _confirmed(settings, "B2", "4006381333931")
    mapping = MappingStore()
    result = publish_confirmed_product_mapping(
        tmp_path / "Inbox", settings, mapping, actor="manager", reason="確認済み",
        now=datetime(2026, 9, 28, tzinfo=UTC),
    )
    assert result["published_count"] == 1
    assert result["unresolved_count"] == 1
    assert result["conflict_count"] == 1
    assert {record.source_product_code for record in mapping.saved[0][1]} == {"A1"}


def test_publication_rejects_when_only_conflicts_or_unconfirmed(tmp_path):
    archive = tmp_path / "Inbox" / "Archive" / "ab" / "abcdef"
    archive.mkdir(parents=True)
    (archive / "stock.csv").write_bytes((
        "商品コード,商品名,明細倉庫コード,明細バラ数\nA1,商品A,EAST,4\n"
    ).encode("cp932"))
    (archive / "shipment.csv").write_bytes((
        "出荷日,商品コード,商品名,JAN,数量\n"
        "2026-09-01,A1,商品A,4901234567894,3\n"
    ).encode("cp932"))
    settings = LocalSettingStore(tmp_path / "settings.sqlite3")
    mapping = SqliteInventoryFoundationStore(tmp_path / "inventory.sqlite3")
    with pytest.raises(ValueError, match="CONFIRMED_EMPTY"):
        publish_confirmed_product_mapping(
            tmp_path / "Inbox", settings, mapping, actor="manager", reason="確認済み",
        )
    _confirmed(settings, "A1", "4901234567894")
    result = publish_confirmed_product_mapping(
        tmp_path / "Inbox", settings, mapping, actor="manager", reason="確認済み",
    )
    assert result["published_count"] == 1
    stored = mapping.list_product_mappings(result["product_mapping_version"])
    assert len(stored) == 1 and stored[0].jan == "4901234567894"
