"""確認済み商品の原本出荷数量を、版付き条件で参考試算する。"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ..inventory_foundation.domain import validate_jan
from ..providers.baseline_algorithms import point_forecast
from .product_review import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_ROWS,
    SHIPMENT_DATE,
    SHIPMENT_HEADERS,
    _encoding,
    unresolved_products,
)


def trial_forecast(inbox_root: Path, settings_store, product_code: str) -> dict:
    review = unresolved_products(inbox_root, settings_store)
    selected = next((item for item in review["confirmed_items"]
                     if item["product_code"] == product_code), None)
    if selected is None:
        raise ValueError("TRIAL_JAN_NOT_CONFIRMED")
    policy_record = settings_store.current("SHIPMENT_TRIAL_POLICY", product_code)
    if policy_record is None:
        return {"status": "NEEDS_REVIEW", "reasons": ["SHIPMENT_TRIAL_POLICY_MISSING"],
                "product_code": product_code, "series": []}
    policy = policy_record["value"]
    if not review["complete"] or selected["evidence_status"] == "JAN_CONFLICT":
        return {"status": "NEEDS_REVIEW", "reasons": [
            "SOURCE_FILES_UNREADABLE" if not review["complete"] else "JAN_CONFLICT",
        ], "product_code": product_code, "series": []}
    if policy["unit"] in {"UNKNOWN", "MIXED"}:
        return {"status": "NEEDS_REVIEW", "reasons": ["SOURCE_UNIT_NOT_SINGLE"],
                "product_code": product_code, "series": [],
                "policy_version": policy_record["version"]}

    archive = inbox_root / "Archive"
    paths = sorted(archive.glob("*/*/*.csv"))
    if len(paths) > MAX_FILES or archive.is_symlink():
        raise ValueError("TRIAL_SOURCE_LIMIT")
    root = archive.resolve(strict=True)
    totals: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    covered_days: set[date] = set()
    source_files = []
    rows_seen = invalid_rows = 0
    for path in paths:
        if (path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink()
                or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES):
            raise ValueError("TRIAL_SOURCE_UNSAFE")
        path.resolve(strict=True).relative_to(root)
        try:
            with path.open("r", encoding=_encoding(path), errors="strict", newline="") as source:
                reader = csv.DictReader(source, strict=True)
                if not SHIPMENT_HEADERS.issubset(reader.fieldnames or ()):
                    continue
                with path.open("rb") as binary:
                    source_files.append({
                        "path_sha256": hashlib.sha256(
                            path.resolve(strict=True).relative_to(root).as_posix().encode("utf-8")
                        ).hexdigest(),
                        "content_sha256": hashlib.file_digest(binary, "sha256").hexdigest(),
                    })
                for row in reader:
                    rows_seen += 1
                    if rows_seen > MAX_ROWS:
                        raise ValueError("TRIAL_ROW_LIMIT")
                    if None in row:
                        if (row.get("JAN") or "").strip() == selected["jan"]:
                            invalid_rows += 1
                        continue
                    raw_date = (row.get("出荷日") or "").strip()
                    if not SHIPMENT_DATE.fullmatch(raw_date):
                        if (row.get("JAN") or "").strip() == selected["jan"]:
                            invalid_rows += 1
                        continue
                    try:
                        day = date.fromisoformat(raw_date[:10].replace("/", "-"))
                    except ValueError:
                        if (row.get("JAN") or "").strip() == selected["jan"]:
                            invalid_rows += 1
                        continue
                    covered_days.add(day)
                    if (row.get("JAN") or "").strip() != selected["jan"]:
                        continue
                    warehouse = (row.get("倉庫コード") or "").strip()
                    try:
                        validate_jan(selected["jan"])
                        quantity = Decimal((row.get("数量") or "").strip())
                    except (ValueError, InvalidOperation):
                        invalid_rows += 1
                        continue
                    if not warehouse or not quantity.is_finite() or quantity < 0:
                        invalid_rows += 1
                        continue
                    totals[(warehouse, day)] += quantity
        except (csv.Error, UnicodeError, OSError) as exc:
            raise ValueError("TRIAL_SOURCE_UNREADABLE") from exc
    if invalid_rows:
        return {"status": "NEEDS_REVIEW", "reasons": ["SHIPMENT_ROWS_INVALID"],
                "product_code": product_code, "invalid_rows": invalid_rows, "series": [],
                "policy_version": policy_record["version"]}

    series = []
    warehouses = sorted({warehouse for warehouse, _ in totals})
    for warehouse in warehouses:
        observed = {day: value for (location, day), value in totals.items()
                    if location == warehouse}
        latest = max(observed)
        window = [latest - timedelta(days=offset) for offset in range(27, -1, -1)]
        values = {
            day: float(observed[day]) if day in observed else
            0.0 if (policy["missing_day"] == "ZERO_WHEN_DAILY_FILE_PRESENT"
                    and day in covered_days) else float("nan")
            for day in window
        }
        available_days = sum(value == value for value in values.values())
        predictions = []
        if available_days >= 7:
            history = pd.Series({pd.Timestamp(day): value for day, value in values.items()})
            for horizon in range(1, 8):
                target = pd.Timestamp(latest + timedelta(days=horizon))
                value = point_forecast(history, target, horizon, "moving_average_28")
                predictions.append({
                    "date": target.date().isoformat(),
                    "source_quantity": round(value, 3) if value is not None else None,
                })
        series.append({
            "warehouse_code": warehouse, "last_observed_day": latest.isoformat(),
            "historical_replay": latest < datetime.now(ZoneInfo("Asia/Tokyo")).date()
            - timedelta(days=7),
            "observed_days_in_window": sum(day in observed for day in window),
            "used_days_in_window": available_days,
            "status": "TRIAL_READY" if predictions else "HISTORY_INSUFFICIENT",
            "days": predictions,
            "history": [
                {
                    "date": day.isoformat(),
                    "quantity": str(observed[day]) if day in observed else
                    "0" if (policy["missing_day"] == "ZERO_WHEN_DAILY_FILE_PRESENT"
                            and day in covered_days) else None,
                    "state": "OBSERVED" if day in observed else
                    "ZERO_BY_CONFIRMED_POLICY" if (
                        policy["missing_day"] == "ZERO_WHEN_DAILY_FILE_PRESENT"
                        and day in covered_days
                    ) else "MISSING",
                }
                for day in window
            ],
        })
    fingerprint = hashlib.sha256(json.dumps(
        {"jan": selected["jan"], "policy_version": policy_record["version"],
         "observations": sorted((warehouse, day.isoformat(), str(quantity))
                                for (warehouse, day), quantity in totals.items()),
         "coverage": sorted(day.isoformat() for day in covered_days),
         "source_files": source_files},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {
        "status": "TRIAL_READY" if any(item["days"] for item in series)
        else "NEEDS_REVIEW",
        "reasons": [] if any(item["days"] for item in series)
        else ["SHIPMENT_HISTORY_INSUFFICIENT"],
        "product_code": product_code, "unit": policy["unit"],
        "missing_day": policy["missing_day"], "policy_version": policy_record["version"],
        "source_fingerprint": fingerprint, "model": "moving_average_28",
        "series": series,
        "note": "参考試算。原本数量の単位換算・在庫との接続・出荷判断には使用しない。",
    }
