"""承認候補と原本全期間を照合し、欠測を残した日次履歴を凍結する。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path


def materialize_history(draft: dict, trial: dict, handoff: dict) -> dict:
    """原本・判断版・在庫証拠と直近28日が一致した場合だけ全履歴を作る。"""

    approved = draft["content"]
    if (trial.get("status") != "TRIAL_READY" or trial.get("unit") != "CASE"
            or trial.get("product_code") != approved["product_code"]
            or trial.get("source_fingerprint") != approved["source_fingerprint"]
            or trial.get("policy_version") != approved["trial_policy_version"]
            or trial.get("missing_day") != approved["missing_day_policy"]
            or handoff.get("jan") != approved["jan"]
            or handoff.get("source_fingerprint") != approved["source_fingerprint"]
            or handoff.get("trial_policy_version") != approved["trial_policy_version"]
            or handoff.get("business_date") != approved["business_date"]):
        raise ValueError("FORMAL_HISTORY_EVIDENCE_CHANGED")
    warehouse = approved["warehouse_code"]
    candidates = [item for item in handoff["series"]
                  if item["warehouse_code"] == warehouse]
    series = [item for item in trial["series"]
              if item["warehouse_code"] == warehouse]
    if (len(candidates) != 1 or not candidates[0]["preparation_candidate"]
            or candidates[0]["inventory_snapshot_id"] != approved["inventory_snapshot_id"]
            or len(series) != 1):
        raise ValueError("FORMAL_HISTORY_SERIES_CHANGED")
    history = series[0].get("full_history")
    if not history or history[-28:] != [
        {"date": row["date"], "quantity": row["quantity_case"],
         "state": row["state"]} for row in approved["daily_rows"]
    ]:
        raise ValueError("FORMAL_HISTORY_DRAFT_MISMATCH")
    first = date.fromisoformat(history[0]["date"])
    if len(history) > 3651:
        raise ValueError("FORMAL_HISTORY_SPAN_LIMIT")
    rows = []
    missing = zero = 0
    for index, row in enumerate(history):
        if date.fromisoformat(row["date"]) != first + timedelta(days=index):
            raise ValueError("FORMAL_HISTORY_DATE_INVALID")
        state, quantity = row["state"], row["quantity"]
        if state == "MISSING":
            if quantity is not None:
                raise ValueError("FORMAL_HISTORY_MISSING_INVALID")
            missing += 1
        elif state in {"OBSERVED", "ZERO_BY_CONFIRMED_POLICY"}:
            try:
                number = Decimal(quantity)
            except (InvalidOperation, TypeError):
                raise ValueError("FORMAL_HISTORY_QUANTITY_INVALID") from None
            if not number.is_finite() or number < 0:
                raise ValueError("FORMAL_HISTORY_QUANTITY_INVALID")
            if state == "ZERO_BY_CONFIRMED_POLICY":
                if number != 0 or approved["missing_day_policy"] != "ZERO_WHEN_DAILY_FILE_PRESENT":
                    raise ValueError("FORMAL_HISTORY_ZERO_INVALID")
                zero += 1
            quantity = str(number)
        else:
            raise ValueError("FORMAL_HISTORY_STATE_INVALID")
        rows.append({"date": row["date"], "quantity_case": quantity, "state": state})
    content = {
        "format_version": 1, "draft_id": draft["draft_id"],
        "product_code": approved["product_code"], "jan": approved["jan"],
        "warehouse_code": warehouse, "unit": "CASE",
        "source_fingerprint": approved["source_fingerprint"],
        "trial_policy_version": approved["trial_policy_version"],
        "inventory_snapshot_id": approved["inventory_snapshot_id"],
        "missing_day_policy": approved["missing_day_policy"],
        "daily_rows": rows,
    }
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "history_id": f"shipment-history-{digest}", "content": content,
        "day_count": len(rows), "missing_day_count": missing,
        "zero_by_policy_day_count": zero, "first_day": rows[0]["date"],
        "last_day": rows[-1]["date"], "daily_build_ready": False,
        "blocking_reasons": (["FULL_HISTORY_MISSING_DAYS"] if missing else [])
        + ["FORMAL_NORMALIZATION_AND_CANONICAL_IDENTITY_REQUIRED"],
    }


class FormalShipmentHistoryStore:
    """個人情報を含み得る日次行はローカルSQLiteにのみ保存する。"""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS formal_shipment_histories (
                history_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL,
                content_json TEXT NOT NULL
            )""")

    def put(self, history: dict) -> dict:
        content = history["content"]
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("INSERT OR IGNORE INTO formal_shipment_histories VALUES (?,?,?)", (
                history["history_id"], content["draft_id"],
                json.dumps(content, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")),
            ))
        return {key: value for key, value in history.items() if key != "content"}

    def get(self, history_id: str) -> dict | None:
        if not re.fullmatch(r"shipment-history-[0-9a-f]{64}", history_id):
            raise ValueError("FORMAL_HISTORY_ID_INVALID")
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT content_json FROM formal_shipment_histories "
                             "WHERE history_id=?", (history_id,)).fetchone()
        if row is None:
            return None
        content = json.loads(row[0])
        canonical = json.dumps(content, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if "shipment-history-" + digest != history_id:
            raise ValueError("FORMAL_HISTORY_INTEGRITY_INVALID")
        return content
