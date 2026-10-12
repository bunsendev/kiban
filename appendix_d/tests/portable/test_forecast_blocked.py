import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from portable.api.business_archive import ArchiveError, analyze_archive
from portable.api.daily_auto_run import PortableDailyAutoRun
from portable.api.formal_shipment_daily import sha256
from portable.api.production_handoff import PortableProductionHandoff, ProductionHandoffError


def test_valid_blocked_build_is_not_corruption(tmp_path):
    build_id = "portable-daily-" + "a" * 64
    root = tmp_path / build_id
    root.mkdir()
    daily = b"ds,unique_id,y\n"
    (root / "daily.csv").write_bytes(daily)
    (root / "manifest.json").write_text(json.dumps({
        "build_id": build_id, "daily_data_sha256": sha256(daily), "status": "BLOCKED"
    }), encoding="utf-8")
    service = PortableProductionHandoff.__new__(PortableProductionHandoff)
    service.paths = SimpleNamespace(formal_forecast=tmp_path)
    with pytest.raises(ProductionHandoffError, match="予測対象がありません"):
        service._verified_source(build_id)
    (root / "daily.csv").write_bytes(daily + b"tampered")
    with pytest.raises(ProductionHandoffError, match="整合性"):
        service._verified_source(build_id)


def test_blocked_daily_build_never_queues_production():
    service = PortableDailyAutoRun.__new__(PortableDailyAutoRun)
    current = {"status": "FORECAST_CONFIRMATION_REQUIRED", "handoff_id": "artificial"}
    blocked = {"status": "FORECAST_BLOCKED", "blocked_series_count": 1}
    service.view = Mock(side_effect=[current, blocked])
    service.pipeline = SimpleNamespace(view=Mock(return_value={
        "latest_covers_all": True, "latest": {
            "registration_id": "artificial", "status": "APPROVED", "jobs": []
        }
    }))
    service.forecast = SimpleNamespace(run=Mock(return_value={"status": "BLOCKED"}))
    service.production = SimpleNamespace(enqueue=Mock())
    payload = {"actor": "人工", "reason": "人工検証", **dict.fromkeys([
        "confirm_pilot_scope", "confirm_quantity_reconciliation",
        "confirm_identity_bridge", "confirm_zero_policy"
    ], True)}
    assert service._advance("artificial", payload) == blocked
    service.production.enqueue.assert_not_called()


def test_inventory_only_export_explains_next_action(tmp_path):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "format": "portable-formal-inventory-handoff-v1"
        }))
    with pytest.raises(ArchiveError, match="正式在庫取込専用"):
        analyze_archive(raw.getvalue(), tmp_path / "prepared.csv")
