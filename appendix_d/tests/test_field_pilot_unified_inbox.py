"""投入順序・重複・訂正・未知形式でShadowへの誤通過を防ぐ。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from forecast_provider.field_pilot.inbox_classifier import header_sha256
from forecast_provider.field_pilot.inbox_ledger import InboxLedger
from forecast_provider.field_pilot.inbox_policy import load_inbox_policy
from forecast_provider.field_pilot.inbox_processor import InboxProcessor


def _policy(root: Path):
    day = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    headers = ("day", "warehouse", "cases")
    path = root / "inbox-policy.json"
    path.write_text(json.dumps({
        "format": "field-pilot-inbox-v1", "version": "v1",
        "required": [{"kind": "WAREHOUSE_INVENTORY", "location_id": "EAST",
                      "display_name": "東倉庫在庫"}],
        "rules": [{"schema_id": "east-v1", "kind": "WAREHOUSE_INVENTORY",
                   "location_id": "EAST", "header_sha256": header_sha256(headers),
                   "required_columns": list(headers), "date_column": "day",
                   "date_format": "%Y-%m-%d", "quantity_column": "cases",
                   "location_column": "warehouse"}],
    }), encoding="utf-8")
    return load_inbox_policy(path), day


def _stage(root: Path, name: str, data: bytes) -> None:
    stage = uuid.uuid4().hex
    staged = root / "Staged"
    staged.mkdir(exist_ok=True)
    (staged / f"{stage}.bin").write_bytes(data)
    (staged / f"{stage}.json").write_text(json.dumps({
        "original_name": name, "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data), "received_at": datetime.now().astimezone().isoformat(),
    }), encoding="utf-8")


def test_inbox_requires_strict_import_before_ready_and_deduplicates(tmp_path):
    policy, day = _policy(tmp_path)
    root = tmp_path / "Inbox"
    root.mkdir()
    ledger = InboxLedger(root / "inbox.sqlite3")
    data = f"day,warehouse,cases\n{day},EAST,4\n".encode()
    _stage(root, "anything.csv", data)
    processor = InboxProcessor(root, policy, ledger)
    assert processor.scan() == 1
    summary = ledger.summary(policy, day)
    assert summary["status"] == "MISSING_OR_REVIEW"
    assert summary["required"][0]["status"] == "RECEIVED"
    assert summary["received_count"] == 1
    assert processor.scan() == 0
    _stage(root, "renamed.csv", data)
    assert processor.scan() == 1
    assert ledger.summary(policy, day)["duplicate_count"] == 1


def test_revision_and_header_change_cannot_replace_approved_data(tmp_path):
    policy, day = _policy(tmp_path)
    root = tmp_path / "Inbox"
    root.mkdir()
    ledger = InboxLedger(root / "inbox.sqlite3")
    processor = InboxProcessor(root, policy, ledger, lambda *_: True)
    _stage(root, "inventory.csv", f"day,warehouse,cases\n{day},EAST,4\n".encode())
    processor.scan()
    assert ledger.summary(policy, day)["status"] == "READY"
    _stage(root, "changed.csv", f"day,warehouse,cases\n{day},EAST,5\n".encode())
    processor.scan()
    summary = ledger.summary(policy, day)
    assert summary["required"][0]["status"] == "REVIEW_REQUIRED"
    assert summary["status"] != "READY"
    _stage(root, "header.csv", f"day,warehouse,new_cases\n{day},EAST,5\n".encode())
    _stage(root, "mystery.pdf", b"%PDF-1.4\n")
    processor.scan()
    assert ledger.summary(policy, day)["review_count"] >= 3


def test_unknown_extra_file_blocks_even_when_required_set_was_valid(tmp_path):
    policy, day = _policy(tmp_path)
    root = tmp_path / "Inbox"
    root.mkdir()
    ledger = InboxLedger(root / "inbox.sqlite3")
    processor = InboxProcessor(root, policy, ledger, lambda *_: True)
    _stage(root, "inventory.csv", f"day,warehouse,cases\n{day},EAST,4\n".encode())
    processor.scan()
    assert ledger.summary(policy, day)["status"] == "READY"
    _stage(root, "unexpected.csv", b"unfamiliar,header\nx,y\n")
    processor.scan()
    assert ledger.summary(policy, day)["status"] == "MISSING_OR_REVIEW"


def test_new_policy_can_reclassify_previous_unknown_same_sha(tmp_path):
    policy, day = _policy(tmp_path)
    root = tmp_path / "Inbox"
    root.mkdir()
    ledger = InboxLedger(root / "inbox.sqlite3")
    data = f"date,site,quantity\n{day},EAST,4\n".encode()
    _stage(root, "unknown.csv", data)
    InboxProcessor(root, policy, ledger).scan()
    assert ledger.summary(policy, day)["status"] != "READY"

    path = tmp_path / "inbox-policy.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = "v2"
    payload["rules"] = [{
        **payload["rules"][0], "schema_id": "east-v2",
        "header_sha256": header_sha256(("date", "site", "quantity")),
        "required_columns": ["date", "site", "quantity"],
        "date_column": "date", "location_column": "site",
        "quantity_column": "quantity",
    }]
    path.write_text(json.dumps(payload), encoding="utf-8")
    revised = load_inbox_policy(path)
    _stage(root, "unknown.csv", data)
    InboxProcessor(root, revised, ledger, lambda *_: True).scan()
    assert ledger.summary(revised, day)["status"] == "READY"


def test_incomplete_stage_and_tampered_checksum_never_import(tmp_path):
    policy, day = _policy(tmp_path)
    root = tmp_path / "Inbox"
    root.mkdir()
    ledger = InboxLedger(root / "inbox.sqlite3")
    called = []
    processor = InboxProcessor(root, policy, ledger, lambda *args: called.append(args) or True)
    data = f"day,warehouse,cases\n{day},EAST,4\n".encode()
    _stage(root, "inventory.csv", data)
    (next((root / "Staged").glob("*.bin"))).write_bytes(data + b"tamper")
    processor.scan()
    assert called == []
    assert ledger.summary(policy, day)["status"] != "READY"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShellの排他stageを検証")
def test_windows_stage_detects_same_size_same_mtime_revision(tmp_path):
    drop = tmp_path / "Inbox" / "Drop"
    drop.mkdir(parents=True)
    source = drop / "input.csv"
    source.write_bytes(b"day,warehouse,cases\n2026-09-28,EAST,4\n")
    timestamp = source.stat()
    script = Path(__file__).parents[1] / "installer/windows/field-pilot-inbox-stage.ps1"

    def scan():
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(script), "-DataRoot", str(tmp_path)],
            capture_output=True, check=True,
        )
        return len(list((tmp_path / "Inbox" / "Staged").glob("*.json")))

    assert scan() == 1
    assert scan() == 1
    source.write_bytes(b"day,warehouse,cases\n2026-09-28,EAST,5\n")
    os.utime(source, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
    assert scan() == 2
