"""Daily intake version isolation, legacy restart and immutable downstream contracts."""

import hashlib
import io
import json
import sqlite3
import zipfile
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forecast_provider.inventory_foundation import (
    InventoryLocation,
    LocationMasterVersion,
    LocationType,
    SqliteInventoryFoundationStore,
)
from portable.api.app import create_app
from portable.api.formal_pipeline import PortableFormalPipeline
from portable.api.formal_pipeline_contracts import prepare_pipeline
from portable.api.inventory_handoff import HEADERS, _mapping
from portable.api.inventory_versions import mapping_identity
from portable.runtime.paths import DataPaths

CONFIRM = {
    "actor": "テスト担当",
    "reason": "数量・対象・対応・0日を確認",
    "confirm_pilot_scope": True,
    "confirm_quantity_reconciliation": True,
    "confirm_identity_bridge": True,
    "confirm_zero_policy": True,
}


def _jan(index):
    body = f"4901234{index:05d}"
    check = -sum(int(v) * (1 if i % 2 == 0 else 3) for i, v in enumerate(body)) % 10
    return body + str(check)


def _archive(day, count=1, *, complete=True):
    target = io.BytesIO()
    inventory = ["商品コード,商品名,明細バラ数,賞味期限"]
    inventory += [f"{_jan(i)},人工商品{i},{10 + i},2026/12/31" for i in range(count)]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"神戸日時在庫_202609{day:02d}.csv", "\n".join(inventory).encode("cp932"))
        for n in range(1, day + 1) if complete else [day]:
            rows = ["出荷日,納品日,商品名,JAN,数量"]
            rows += [
                f"2026/09/{n:02d},2026/09/{n:02d},人工商品{i},{_jan(i)},2" for i in range(count)
            ]
            z.writestr(f"神戸日時出荷_202609{n:02d}.csv", "\n".join(rows).encode("cp932"))
    return target.getvalue()


def _prepare(client, day, count=1, *, code="KOBE", complete=True):
    r = client.post(
        "/api/business-archives",
        content=_archive(day, count, complete=complete),
        headers={"Content-Type": "application/zip"},
    )
    assert r.status_code == 201, r.text
    analysis = r.json()["analysis_id"]
    r = client.post(
        f"/api/business-archives/{analysis}/formal-inventory",
        json={
            "actor": "テスト担当",
            "reason": "原本と数量確認",
            "confirm_case": True,
            "locations": [
                {
                    "source_center": "神戸",
                    "location_code": code,
                    "location_name": "人工倉庫",
                    "snapshot_time": "16:00",
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "READY_FOR_FORMAL_INTAKE", r.text
    return analysis, r.json()


def _advance(client, analysis):
    r = client.post(f"/api/daily-runs/{analysis}/advance", json=CONFIRM)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize("days", [(1, 2, 3), (3, 2, 1)])
def test_sequential_and_reverse_daily_intakes_keep_prior_versions(tmp_path: Path, days):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    versions = []
    latest_days = []
    for day in days:
        latest_day = max(days[: days.index(day) + 1])
        latest_days.append(latest_day)
        analysis, handoff = _prepare(client, day)
        result = _advance(client, analysis)
        assert result["status"] == "FORECAST_BLOCKED"
        blocker = result["blockers"][0]
        assert blocker["recognized_required_days"] == latest_day
        assert len(blocker["missing_required_dates"]) == 28 - latest_day
        assert blocker["reason_codes"] == ["HISTORY_LESS_THAN_28_DAYS"]
        versions.append(handoff["location_master_version"])
        repeat = _advance(client, analysis)
        assert repeat["registration_id"] == result["registration_id"]
        assert repeat["build_id"] == result["build_id"]
    assert len(set(versions)) == len(set(latest_days))
    store = SqliteInventoryFoundationStore(tmp_path / "State/formal-pipeline.sqlite3")
    for day, version in zip(latest_days, versions, strict=True):
        assert store.list_locations(version)[0].effective_from == date(2026, 9, day)


@pytest.mark.parametrize("change", ["products", "warehouse", "reviewer"])
def test_same_day_changed_scope_code_or_reviewer_is_not_an_identity_collision(
    tmp_path: Path, change
):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    if change == "products":
        analysis, first = _prepare(client, 2, 2)
        second = first
        endpoint = f"/api/formal-inventory/{first['handoff_id']}/pipeline"
        for selected in ([_jan(0)], [_jan(0), _jan(1)]):
            r = client.post(
                endpoint,
                json={
                    "actor": "テスト担当",
                    "reason": "対象範囲確認",
                    "confirm_pilot_scope": True,
                    "selections": [{"source_center": "神戸", "jans": selected}],
                },
            )
            assert r.status_code == 201, r.text
            assert r.json()["jobs"][0]["accepted_row_count"] == len(selected)
        original = r.json()
    else:
        analysis, first = _prepare(client, 2)
        original = _advance(client, analysis)
        analysis, second = _prepare(client, 2, code="KOBE2" if change == "warehouse" else "KOBE")
    if change == "reviewer":
        r = client.post(
            f"/api/formal-inventory/{second['handoff_id']}/pipeline",
            json={
                "actor": "別の確認者",
                "reason": "別理由で再確認",
                "confirm_pilot_scope": True,
                "selections": [{"source_center": "神戸", "jans": [_jan(0)]}],
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["jobs"][0]["snapshot_id"]
    result = _advance(client, analysis)
    assert result["status"] == "FORECAST_BLOCKED"
    if change == "products":
        assert len(result["blockers"]) == 2
        assert first["location_master_version"] == second["location_master_version"]
    if change == "warehouse":
        assert first["location_master_version"] != second["location_master_version"]
    assert original["registration_id"]


def test_legacy_cached_handoff_resumes_without_rewriting_old_master_or_manifest(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    analysis, handoff = _prepare(client, 2)

    def canonical(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    old_version = (
        "portable-locations-" + hashlib.sha256(canonical(handoff["locations"])).hexdigest()[:24]
    )
    old_mapping = (
        "portable-inventory-map-"
        + hashlib.sha256(
            canonical(
                {
                    "location_master_version": old_version,
                    "headers": HEADERS,
                    "unit": "CASE",
                }
            )
        ).hexdigest()[:24]
    )
    store = SqliteInventoryFoundationStore(tmp_path / "State/formal-pipeline.sqlite3")
    now = datetime.now(UTC)
    location = handoff["locations"][0]
    store.put_location_master(
        LocationMasterVersion(old_version, "a" * 64, "旧版", "9/1登録", now),
        (
            InventoryLocation(
                old_version,
                location["location_id"],
                "KOBE",
                "人工倉庫",
                LocationType.WAREHOUSE,
                date(2026, 9, 1),
            ),
        ),
    )
    store.put_mapping(_mapping(old_mapping, old_version, "旧版", "9/1登録", now))
    handoff.update(location_master_version=old_version, mapping_version=old_mapping)
    manifest = tmp_path / "FormalInventory" / handoff["handoff_id"] / "manifest.json"
    manifest.write_bytes(canonical(handoff))
    original = manifest.read_bytes()
    result = _advance(client, analysis)
    assert result["status"] == "FORECAST_BLOCKED"
    assert result["blockers"][0]["recognized_required_days"] == 2
    assert manifest.read_bytes() == original
    assert store.list_locations(old_version)[0].effective_from == date(2026, 9, 1)
    assert store.get_mapping(old_mapping).location_master_version == old_version
    registration = json.loads(
        (
            tmp_path / "FormalInventory/Registrations" / (result["registration_id"] + ".json")
        ).read_text("utf-8")
    )
    assert registration["source_location_master_version"] == old_version
    assert registration["location_master_version"] != old_version
    assert registration["source_mapping_version"] == old_mapping
    assert registration["mapping_version"] != old_mapping
    restarted = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert _advance(restarted, analysis)["registration_id"] == result["registration_id"]


def test_full_history_and_next_day_reach_forecast_without_downstream_identity_conflicts(
    tmp_path: Path,
):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    prior = None
    for day in (27, 28, 29):
        analysis, _ = _prepare(client, day)
        result = _advance(client, analysis)
        if day == 27:
            assert result["status"] == "FORECAST_BLOCKED"
            assert len(result["blockers"][0]["missing_required_dates"]) == 1
            continue
        assert result["eligible_series_count"] == 1
        assert not result["blockers"]
        path = tmp_path / "FormalForecast" / result["build_id"] / "manifest.json"
        before = path.read_bytes()
        forecast = json.loads(before)
        assert len(forecast["predictions"]) == 14
        assert forecast["series"][0]["recognized_required_days"] == 28
        assert _advance(client, analysis)["build_id"] == result["build_id"]
        assert path.read_bytes() == before
        if prior:
            assert prior[0].read_bytes() == prior[1]
        prior = path, before
    with sqlite3.connect(tmp_path / "State/formal-pipeline.sqlite3") as db:
        assert (
            db.execute("SELECT COUNT(*) FROM inventory_forecast_bridge_versions").fetchone()[0] == 3
        )


def test_mapping_identity_covers_source_column_but_not_audit_metadata():
    now = datetime.now(UTC)
    mapping = _mapping("pending", "location-v1", "担当", "確認", now)
    assert mapping_identity(mapping) == mapping_identity(
        replace(mapping, created_by="別担当", reason="再確認", created_at=now + timedelta(days=1))
    )
    assert mapping_identity(mapping) != mapping_identity(
        replace(mapping, source_quantity_column_name="原本の別数量列")
    )
    assert mapping_identity(mapping) != mapping_identity(
        replace(mapping, location_master_version="location-v2")
    )


def test_conflicting_same_day_source_still_requires_explicit_resolution(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    analysis, _ = _prepare(client, 2)
    before = _advance(client, analysis)
    r = client.post(
        "/api/business-archives",
        content=_archive(2, 2),
        headers={"Content-Type": "application/zip"},
    )
    assert r.status_code == 422
    assert "異なるCSV" in r.json()["detail"]
    assert _advance(client, analysis)["build_id"] == before["build_id"]


def test_pipeline_policy_identity_changes_with_mapping_contract(tmp_path: Path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    _, handoff = _prepare(client, 2)
    pipeline = PortableFormalPipeline(DataPaths(tmp_path))
    approved = {
        "actor": "担当",
        "reason": "確認",
        "selections": [{"source_center": "神戸", "jans": [_jan(0)]}],
    }
    kwargs = {
        "created_at": datetime.now(UTC),
        "inventory_store": pipeline.inventory_store,
        "scope_store": pipeline.scope_store,
    }
    package = tmp_path / "FormalInventory" / handoff["handoff_id"]
    first = prepare_pipeline(handoff, package, approved, **kwargs)
    second = prepare_pipeline(
        {**handoff, "source_quantity_column_name": "別の原本数量列"}, package, approved, **kwargs
    )
    assert first.location_version == second.location_version
    assert first.scopes == second.scopes
    assert first.mapping.mapping_version != second.mapping.mapping_version
    assert first.intakes[0].intake_version != second.intakes[0].intake_version
    assert first.policy.version != second.policy.version
    repeated = prepare_pipeline(handoff, package, approved, **kwargs)
    assert repeated.policy == first.policy


def test_restart_after_registration_receipt_write_failure_is_idempotent(
    tmp_path: Path, monkeypatch
):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    _, handoff = _prepare(client, 2)
    pipeline = PortableFormalPipeline(DataPaths(tmp_path))
    payload = {
        "actor": "担当",
        "reason": "再開確認",
        "confirm_pilot_scope": True,
        "selections": [{"source_center": "神戸", "jans": [_jan(0)]}],
    }
    original = pipeline._atomic_json

    def fail_receipt(path, value):
        if path.parent.name == "Registrations":
            raise OSError("simulated interruption before receipt")
        original(path, value)

    monkeypatch.setattr(pipeline, "_atomic_json", fail_receipt)
    with pytest.raises(OSError, match="simulated interruption"):
        pipeline.register(handoff["handoff_id"], payload)
    monkeypatch.undo()
    restarted = PortableFormalPipeline(DataPaths(tmp_path))
    result = restarted.register(handoff["handoff_id"], payload)
    assert result["status"] == "APPROVAL_REQUIRED"
    assert result["jobs"][0]["accepted_row_count"] == 1
    assert len(restarted.inventory_store.list_snapshots(result["jobs"][0]["job_id"])) == 1
    repeated = restarted.register(handoff["handoff_id"], payload)
    assert repeated["registration_id"] == result["registration_id"]
    assert repeated["jobs"][0]["snapshot_id"] == result["jobs"][0]["snapshot_id"]
