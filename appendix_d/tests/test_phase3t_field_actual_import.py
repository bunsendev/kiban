"""実績CSVの時点・欠測・訂正・原子的batchを検証。"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

import pytest

from forecast_provider.field_actuals import FieldActualImporter
from forecast_provider.field_actuals.cli import main as import_main
from forecast_provider.field_learning import FieldLearningConflict, build_actual_outcome_event
from tests.test_phase3ta0_pilot_gate_foundation import (
    BUSINESS_DATE,
    NOW,
    _reference,
    _service,
)

HEADER = (
    "case_id,expected_revision,unit,actual_shipped_quantity,actual_demand_quantity,"
    "stockout_quantity,expired_quantity,interwarehouse_transfer_quantity\n"
)


def _csv(*rows):
    return (HEADER + "".join(",".join(row) + "\n" for row in rows)).encode("utf-8")


def _row(case_id, revision="0", shipped="3", demand="", stockout="0", unit="CASE"):
    return (case_id, revision, unit, shipped, demand, stockout, "", "")


def _prepare(importer, content, *, version="actual-v1", days=1):
    return importer.prepare(
        content, source_version=version, known_at=NOW + timedelta(days=days),
        recorded_at=NOW + timedelta(days=days, minutes=1),
    )


def test_dry_run_preserves_null_and_zero_then_appends_correction(tmp_path):
    service, store, scope, bridge = _service(tmp_path)
    case = _reference(service, scope, bridge)
    importer = FieldActualImporter(store)
    content = _csv(_row(case.case_id))
    plan = _prepare(importer, content)
    assert plan.source_sha256 == hashlib.sha256(content).hexdigest()
    assert store.list_actual_outcomes(case.case_id) == []
    assert plan.events[0].actual_demand_quantity is None
    assert plan.events[0].stockout_quantity == Decimal("0")
    importer.apply(plan)
    corrected = _prepare(
        importer, _csv(_row(case.case_id, "1", "4", "5", "0")),
        version="actual-v2", days=2,
    )
    importer.apply(corrected)
    events = store.list_actual_outcomes(case.case_id)
    assert [event.revision for event in events] == [1, 2]
    assert events[0].actual_demand_quantity is None
    assert events[1].actual_demand_quantity == Decimal("5")


def test_invalid_second_row_does_not_write_first(tmp_path):
    service, store, scope, bridge = _service(tmp_path)
    first = _reference(service, scope, bridge)
    second = _reference(
        service, scope, bridge, business_date=BUSINESS_DATE + timedelta(days=1)
    )
    importer = FieldActualImporter(store)
    with pytest.raises(ValueError, match="3行目"):
        _prepare(importer, _csv(_row(first.case_id), _row(second.case_id, shipped="-1")))
    assert store.list_actual_outcomes(first.case_id) == []
    assert store.list_actual_outcomes(second.case_id) == []


def test_concurrent_revision_change_rolls_back_entire_batch(tmp_path):
    service, store, scope, bridge = _service(tmp_path)
    first = _reference(service, scope, bridge)
    second = _reference(
        service, scope, bridge, business_date=BUSINESS_DATE + timedelta(days=1)
    )
    importer = FieldActualImporter(store)
    plan = _prepare(importer, _csv(_row(first.case_id), _row(second.case_id)))
    store.append_actual_outcome(build_actual_outcome_event(
        case_id=second.case_id, expected_revision=0, source_version="other",
        source_sha256="a" * 64, actual_shipped_quantity="2",
        actual_demand_quantity=None, stockout_quantity=None,
        expired_quantity=None, interwarehouse_transfer_quantity=None,
        known_at=NOW + timedelta(days=1),
        recorded_at=NOW + timedelta(days=1, minutes=1),
    ), 0)
    with pytest.raises(FieldLearningConflict, match="先に"):
        importer.apply(plan)
    assert store.list_actual_outcomes(first.case_id) == []
    assert len(store.list_actual_outcomes(second.case_id)) == 1


def test_duplicate_missing_and_stale_inputs_fail_closed(tmp_path):
    service, store, scope, bridge = _service(tmp_path)
    case = _reference(service, scope, bridge)
    importer = FieldActualImporter(store)
    with pytest.raises(ValueError, match="重複"):
        _prepare(importer, _csv(_row(case.case_id), _row(case.case_id)))
    with pytest.raises(ValueError, match="存在しません"):
        _prepare(importer, _csv(_row("missing")))
    with pytest.raises(ValueError, match="数量"):
        _prepare(importer, _csv(_row(case.case_id, shipped="", stockout="")))
    with pytest.raises(ValueError, match="known_atがreferenceより前"):
        importer.prepare(
            _csv(_row(case.case_id)), source_version="old",
            known_at=NOW - timedelta(seconds=1), recorded_at=NOW,
        )
    with pytest.raises(ValueError, match="unitはCASE"):
        _prepare(importer, _csv(_row(case.case_id, unit="EACH")))
    with pytest.raises(ValueError, match="CSV列"):
        _prepare(importer, b"case_id,quantity\nmissing,1\n")


def test_cli_defaults_to_dry_run_and_requires_apply(tmp_path, capsys):
    service, store, scope, bridge = _service(tmp_path)
    case = _reference(service, scope, bridge)
    source = tmp_path / "actual.csv"
    source.write_bytes(_csv(_row(case.case_id)))
    args = [
        "--sqlite", str(tmp_path / "pilot.sqlite3"), "--csv", str(source),
        "--source-version", "actual-v1",
        "--known-at", (NOW + timedelta(days=1)).isoformat(),
        "--recorded-at", (NOW + timedelta(days=1, minutes=1)).isoformat(),
    ]
    assert import_main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "DRY_RUN"
    assert store.list_actual_outcomes(case.case_id) == []
    assert import_main([*args, "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "APPLIED"
    assert len(store.list_actual_outcomes(case.case_id)) == 1
