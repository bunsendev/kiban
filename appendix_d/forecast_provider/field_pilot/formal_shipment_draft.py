"""確認済み出荷日次行を、正式buildへ渡す前の不変な候補として保存する。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def make_formal_shipment_draft(
    trial: dict, handoff: dict, *, warehouse_code: str,
    expected_source_fingerprint: str, expected_policy_version: str,
    expected_inventory_snapshot_id: str, actor: str, reason: str,
    approved_at: datetime | None = None,
) -> dict:
    """再計算した証拠が画面の確認対象と完全一致するときだけ日次行を凍結する。"""

    now = approved_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("FORMAL_SHIPMENT_TIME_INVALID")
    if not IDENTIFIER.fullmatch(actor) or not reason.strip() or len(reason) > 500:
        raise ValueError("FORMAL_SHIPMENT_APPROVAL_INVALID")
    if not IDENTIFIER.fullmatch(warehouse_code):
        raise ValueError("FORMAL_SHIPMENT_WAREHOUSE_INVALID")
    if not FINGERPRINT.fullmatch(expected_source_fingerprint):
        raise ValueError("FORMAL_SHIPMENT_FINGERPRINT_INVALID")
    if (trial.get("status") != "TRIAL_READY" or trial.get("unit") != "CASE"
            or trial.get("source_fingerprint") != expected_source_fingerprint
            or trial.get("policy_version") != expected_policy_version
            or handoff.get("source_fingerprint") != expected_source_fingerprint
            or handoff.get("trial_policy_version") != expected_policy_version
            or handoff.get("product_code") != trial.get("product_code")):
        raise ValueError("FORMAL_SHIPMENT_SOURCE_STALE")

    candidates = [item for item in handoff["series"]
                  if item["warehouse_code"] == warehouse_code]
    trial_series = [item for item in trial["series"]
                    if item["warehouse_code"] == warehouse_code]
    if (len(candidates) != 1 or not candidates[0]["preparation_candidate"]
            or candidates[0]["inventory_snapshot_id"] != expected_inventory_snapshot_id
            or len(trial_series) != 1):
        raise ValueError("FORMAL_SHIPMENT_SERIES_NOT_READY")

    business_date = date.fromisoformat(handoff["business_date"])
    latest = date.fromisoformat(trial_series[0]["last_observed_day"])
    if latest < business_date - timedelta(days=1) or latest > business_date:
        raise ValueError("FORMAL_SHIPMENT_HISTORY_STALE")
    history = trial_series[0].get("history", [])
    if len(history) != 28:
        raise ValueError("FORMAL_SHIPMENT_COVERAGE_INVALID")
    rows = []
    for index, item in enumerate(history):
        if date.fromisoformat(item["date"]) != latest - timedelta(days=27 - index):
            raise ValueError("FORMAL_SHIPMENT_COVERAGE_INVALID")
        if item["state"] not in {"OBSERVED", "ZERO_BY_CONFIRMED_POLICY"}:
            raise ValueError("FORMAL_SHIPMENT_COVERAGE_INVALID")
        try:
            quantity = Decimal(item["quantity"])
        except (InvalidOperation, TypeError):
            raise ValueError("FORMAL_SHIPMENT_QUANTITY_INVALID") from None
        if not quantity.is_finite() or quantity < 0:
            raise ValueError("FORMAL_SHIPMENT_QUANTITY_INVALID")
        if item["state"] == "ZERO_BY_CONFIRMED_POLICY" and (
            quantity != 0 or trial["missing_day"] != "ZERO_WHEN_DAILY_FILE_PRESENT"
        ):
            raise ValueError("FORMAL_SHIPMENT_ZERO_INVALID")
        rows.append({"date": item["date"], "quantity_case": str(quantity),
                     "state": item["state"]})

    content = {
        "format_version": 1, "product_code": trial["product_code"],
        "jan": handoff["jan"], "warehouse_code": warehouse_code,
        "unit": "CASE", "business_date": handoff["business_date"],
        "source_fingerprint": expected_source_fingerprint,
        "trial_policy_version": expected_policy_version,
        "inventory_snapshot_id": expected_inventory_snapshot_id,
        "missing_day_policy": trial["missing_day"], "daily_rows": rows,
    }
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {"draft_id": f"shipment-draft-{digest}", "content": content,
            "approved_by": actor, "approval_reason": reason.strip(),
            "approved_at": now.astimezone(UTC).isoformat(),
            "daily_build_ready": False,
            "next_gate": "FORMAL_NORMALIZATION_IDENTITY_AND_DAILY_BUILD_REQUIRED"}


class FormalShipmentDraftStore:
    """内容アドレスの候補をローカルに追記し、同一入力の重複作成を防ぐ。"""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS formal_shipment_drafts (
                draft_id TEXT PRIMARY KEY, content_json TEXT NOT NULL,
                approved_by TEXT NOT NULL, approval_reason TEXT NOT NULL,
                approved_at TEXT NOT NULL
            )""")

    def put(self, draft: dict) -> dict:
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("INSERT OR IGNORE INTO formal_shipment_drafts VALUES (?,?,?,?,?)", (
                draft["draft_id"], json.dumps(draft["content"], ensure_ascii=False,
                                              sort_keys=True, separators=(",", ":")),
                draft["approved_by"], draft["approval_reason"], draft["approved_at"],
            ))
            row = db.execute("SELECT * FROM formal_shipment_drafts WHERE draft_id=?",
                             (draft["draft_id"],)).fetchone()
        return {"draft_id": row[0], "content": json.loads(row[1]),
                "approved_by": row[2], "approval_reason": row[3],
                "approved_at": row[4], "daily_build_ready": False,
                "next_gate": "FORMAL_NORMALIZATION_IDENTITY_AND_DAILY_BUILD_REQUIRED"}

    def get(self, draft_id: str) -> dict | None:
        if not re.fullmatch(r"shipment-draft-[0-9a-f]{64}", draft_id):
            raise ValueError("FORMAL_SHIPMENT_DRAFT_ID_INVALID")
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT * FROM formal_shipment_drafts WHERE draft_id=?", (draft_id,),
            ).fetchone()
        if row is None:
            return None
        content = json.loads(row[1])
        canonical = json.dumps(content, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        if f"shipment-draft-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}" != row[0]:
            raise ValueError("FORMAL_SHIPMENT_DRAFT_CORRUPT")
        return {"draft_id": row[0], "content": content,
                "approved_by": row[2], "approval_reason": row[3],
                "approved_at": row[4]}
