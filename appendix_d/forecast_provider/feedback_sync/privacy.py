"""改善イベントを許可済みの集計・疑似IDだけへ変換する。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

from ..field_pilot.improvement_events import ERROR_CODES, EVENT_TYPES, METRIC_KEYS, OUTCOMES
from .policy import validate_policy
from .signals import CHANGE_TYPES, LEARNING_ACTIONS

SAFE_METRICS = METRIC_KEYS - {"row_count", "item_count", "shortage_count",
                             "expiry_attention_count", "size_bytes"}
QUANTITY_METRICS = METRIC_KEYS - SAFE_METRICS
MANIFEST_FIELDS = (
    "contains_raw_files", "contains_product_names", "contains_jan",
    "contains_customer_names", "contains_absolute_inventory",
    "contains_pseudonymous_product_id", "contains_forecast_error",
)


def pseudonym(secret: bytes, client_id: str, kind: str, value: str) -> str:
    if len(secret) < 32 or not client_id or kind not in {"PRODUCT", "WAREHOUSE"} or not value:
        raise ValueError("FEEDBACK_PSEUDONYM_INVALID")
    message = f"{client_id}\x00{kind}\x00{value}".encode()
    return f"{kind}_{hmac.new(secret, message, hashlib.sha256).hexdigest()[:32]}"


def collect_events(path: Path, day: date) -> list[dict]:
    if not path.is_file() or path.is_symlink():
        return []
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT event_type,outcome,error_code,metrics_json,jan,location_id "
            "FROM improvement_events WHERE business_date=? ORDER BY event_id LIMIT 10000",
            (day.isoformat(),),
        ).fetchall()
    return [dict(row) for row in rows]


def minimize(rows: list[dict], policy: dict, *, client_id: str,
             secret: bytes | None = None, context: dict | None = None) -> dict:
    value = validate_policy(policy)
    level, flags = value["level"], value["flags"]
    if level == 0:
        return {"event_counts": [], "metric_summary": [], "details": []}
    counts: Counter[tuple[str, str, str | None]] = Counter()
    metrics: dict[tuple[str, str], list[float]] = defaultdict(list)
    details = []
    for row in rows:
        event, outcome, error = row.get("event_type"), row.get("outcome"), row.get("error_code")
        if event not in EVENT_TYPES or outcome not in OUTCOMES or error not in ERROR_CODES | {None}:
            continue
        counts[(event, outcome, error)] += 1
        raw_metrics = json.loads(row.get("metrics_json") or "{}")
        if not isinstance(raw_metrics, dict):
            continue
        for key, raw in raw_metrics.items():
            if (level >= 2 and key in SAFE_METRICS and type(raw) in {int, float}
                    and 0 <= raw < 1e12):
                metrics[(event, key)].append(float(raw))
        if level == 3 and flags["diagnostics"]:
            detail = {"event_type": event, "outcome": outcome, "error_code": error}
            if flags["pseudonymous_products"] and row.get("jan"):
                if secret is None:
                    raise ValueError("FEEDBACK_SECRET_REQUIRED")
                detail["product_id"] = pseudonym(secret, client_id, "PRODUCT", row["jan"])
            if flags["pseudonymous_warehouses"] and row.get("location_id"):
                if secret is None:
                    raise ValueError("FEEDBACK_SECRET_REQUIRED")
                detail["warehouse_id"] = pseudonym(
                    secret, client_id, "WAREHOUSE", row["location_id"],
                )
            allowed = ((SAFE_METRICS if flags["forecast_metrics"] else set())
                       | (QUANTITY_METRICS if flags["absolute_quantities"] else set()))
            detail["metrics"] = {key: raw for key, raw in raw_metrics.items()
                                 if key in allowed and type(raw) in {int, float}
                                 and 0 <= raw < 1e12}
            details.append(detail)
    summary = []
    if flags["diagnostics"]:
        summary = [{"event_type": event, "outcome": outcome, "error_code": error,
                    "count": count} for (event, outcome, error), count in sorted(
                        counts.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or ""),
                    )]
    metric_summary = []
    if level >= 2 and flags["forecast_metrics"]:
        metric_summary = [{"event_type": event, "metric": key,
                           "count": len(numbers), "average": sum(numbers) / len(numbers)}
                          for (event, key), numbers in sorted(metrics.items())]
    if level < 3:
        details = []
    payload = {"event_counts": summary, "metric_summary": metric_summary, "details": details}
    if level >= 2:
        context = context or {}
        if flags["learning_summary"]:
            payload["learning_summary"] = context.get("learning_summary", [])
        if flags["change_summary"]:
            payload["change_summary"] = context.get("change_summary", [])
        if flags["data_freshness"]:
            errors = {row.get("error_code") for row in rows}
            if any(row.get("event_type") == "FORECAST_READY" and row.get("outcome") == "OK"
                   for row in rows):
                payload["data_freshness"] = "FRESH"
            elif errors & {"SNAPSHOT_TOO_OLD", "SNAPSHOT_BUSINESS_DATE_MISMATCH"}:
                payload["data_freshness"] = "STALE"
            elif errors & {"DATA_NOT_READY", "INBOX_NOT_READY"}:
                payload["data_freshness"] = "MISSING"
            elif errors & {"PDF_HUMAN_REVIEW_REQUIRED", "SCHEMA_AMBIGUOUS"}:
                payload["data_freshness"] = "REVIEW_REQUIRED"
    return payload


def manifest(payload: dict, *, policy_version: str, application_version: str) -> dict:
    details = payload.get("details", [])
    result = dict.fromkeys(MANIFEST_FIELDS, False)
    result["contains_pseudonymous_product_id"] = any("product_id" in item for item in details)
    result["contains_absolute_inventory"] = any(
        set(item.get("metrics", {})) & QUANTITY_METRICS for item in details
    )
    result["policy_version"] = policy_version
    result["application_version"] = application_version
    result["created_at"] = datetime.now(UTC).isoformat()
    return result


def validate_package(package: dict, *, max_level: int) -> None:
    if not isinstance(package, dict) or set(package) != {"manifest", "payload", "level"}:
        raise ValueError("FEEDBACK_PACKAGE_INVALID")
    manifest_value, payload = package["manifest"], package["payload"]
    if (type(package["level"]) is not int or not 1 <= package["level"] <= max_level
            or not isinstance(manifest_value, dict) or not isinstance(payload, dict)
            or set(manifest_value) != set(MANIFEST_FIELDS) | {
                "policy_version", "application_version", "created_at",
            }
            or not {"event_counts", "metric_summary", "details"} <= set(payload)
            or set(payload) - {"event_counts", "metric_summary", "details",
                               "learning_summary", "change_summary", "data_freshness"}
            or any(not isinstance(payload[name], list) for name in (
                "event_counts", "metric_summary", "details",
            ))
            or any(manifest_value.get(name) is not False for name in MANIFEST_FIELDS
                   if name not in {"contains_pseudonymous_product_id",
                                   "contains_absolute_inventory"})
            or not isinstance(manifest_value.get("policy_version"), str)
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}",
                                manifest_value["policy_version"])
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}",
                                str(manifest_value["application_version"]))
            or not isinstance(manifest_value.get("created_at"), str)
            or len(manifest_value["created_at"]) > 50):
        raise ValueError("FEEDBACK_PACKAGE_POLICY_REJECTED")
    if package["level"] < 3 and payload["details"]:
        raise ValueError("FEEDBACK_PACKAGE_POLICY_REJECTED")
    if package["level"] < 2 and set(payload) & {
        "learning_summary", "change_summary", "data_freshness",
    }:
        raise ValueError("FEEDBACK_PACKAGE_POLICY_REJECTED")
    for name, allowed in (("learning_summary", LEARNING_ACTIONS),
                          ("change_summary", CHANGE_TYPES)):
        value = payload.get(name, [])
        if not isinstance(value, list) or any(
            not isinstance(item, dict) or set(item) != {"kind", "count"}
            or item["kind"] not in allowed or type(item["count"]) is not int
            or not 0 < item["count"] <= 10000 for item in value
        ):
            raise ValueError("FEEDBACK_PACKAGE_POLICY_REJECTED")
    if payload.get("data_freshness") not in {
        None, "FRESH", "STALE", "MISSING", "REVIEW_REQUIRED",
    }:
        raise ValueError("FEEDBACK_PACKAGE_POLICY_REJECTED")
    if len(json.dumps(package, ensure_ascii=False)) > 1_000_000:
        raise ValueError("FEEDBACK_PACKAGE_TOO_LARGE")
    for item in payload["event_counts"]:
        if (not isinstance(item, dict)
                or set(item) != {"event_type", "outcome", "error_code", "count"}
                or item["event_type"] not in EVENT_TYPES or item["outcome"] not in OUTCOMES
                or item["error_code"] not in ERROR_CODES | {None}
                or type(item["count"]) is not int or not 0 < item["count"] <= 10000):
            raise ValueError("FEEDBACK_PACKAGE_POLICY_REJECTED")
    for item in payload["metric_summary"]:
        if (not isinstance(item, dict)
                or set(item) != {"event_type", "metric", "count", "average"}
                or item["event_type"] not in EVENT_TYPES or item["metric"] not in SAFE_METRICS
                or type(item["count"]) is not int or not 0 < item["count"] <= 10000
                or type(item["average"]) not in {int, float}
                or not 0 <= item["average"] < 1e12):
            raise ValueError("FEEDBACK_PACKAGE_POLICY_REJECTED")
    for detail in payload["details"]:
        if (not isinstance(detail, dict) or
                set(detail) - {"event_type", "outcome", "error_code", "product_id",
                          "warehouse_id", "metrics"}
                or detail.get("event_type") not in EVENT_TYPES
                or detail.get("outcome") not in OUTCOMES
                or detail.get("error_code") not in ERROR_CODES | {None}
                or not isinstance(detail.get("metrics"), dict)
                or set(detail["metrics"]) - METRIC_KEYS
                or any(type(raw) not in {int, float} or not 0 <= raw < 1e12
                       for raw in detail["metrics"].values())
                or ("product_id" in detail and not re.fullmatch(
                    r"PRODUCT_[0-9a-f]{32}", detail["product_id"],
                ))
                or ("warehouse_id" in detail
                    and not re.fullmatch(r"WAREHOUSE_[0-9a-f]{32}",
                                         detail["warehouse_id"]))):
            raise ValueError("FEEDBACK_PACKAGE_POLICY_REJECTED")
    if bool(any("product_id" in item for item in payload["details"])) != (
        manifest_value["contains_pseudonymous_product_id"]
    ):
        raise ValueError("FEEDBACK_MANIFEST_MISMATCH")
    if bool(any(set(item["metrics"]) & QUANTITY_METRICS for item in payload["details"])) != (
        manifest_value["contains_absolute_inventory"]
    ):
        raise ValueError("FEEDBACK_MANIFEST_MISMATCH")
