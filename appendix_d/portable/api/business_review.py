"""Append-only operator decisions for Portable business archive reviews."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

DECISION_ACTIONS = {"MAP_JAN", "ACCEPT_MISSING_EXPIRY", "EXCLUDE"}


class ReviewError(ValueError):
    pass


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(body + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def latest_decisions(path: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for record in _read_jsonl(path):
        issue_id = record.get("issue_id")
        if isinstance(issue_id, str):
            latest[issue_id] = record
    return latest


def decision_history(path: Path) -> list[dict]:
    return _read_jsonl(path)


def review_view(report: dict, journal_path: Path) -> dict:
    decisions = latest_decisions(journal_path)
    issues = []
    pending_rows = resolved_rows = 0
    for source in report.get("issues", []):
        item = dict(source)
        decision = decisions.get(item["issue_id"])
        item["decision"] = decision
        if decision:
            resolved_rows += int(item.get("count", 0))
        else:
            pending_rows += int(item.get("count", 0))
        issues.append(item)
    return {
        **report,
        "issues": issues,
        "review": {
            "pending_items": sum(1 for item in issues if not item["decision"]),
            "pending_rows": pending_rows,
            "resolved_items": sum(1 for item in issues if item["decision"]),
            "resolved_rows": resolved_rows,
            "status": "CONFIRMED_FOR_REFERENCE" if not pending_rows else "PENDING_CONFIRMATION",
        },
    }


def _validate_decision(issue: dict, payload: dict) -> tuple[str, str | None, str]:
    action = str(payload.get("action") or "").strip().upper()
    corrected_jan = str(payload.get("corrected_jan") or "").strip() or None
    note = str(payload.get("note") or "").strip()
    if action not in DECISION_ACTIONS:
        raise ReviewError("判断内容を選択してください")
    if len(note) > 500:
        raise ReviewError("メモは500文字以内にしてください")
    reason = issue["reason"]
    if action == "MAP_JAN":
        if reason not in {"JAN_12_DIGITS", "INVENTORY_CODE_UNMATCHED"}:
            raise ReviewError("この項目はJAN対応付けできません")
        if not corrected_jan or not corrected_jan.isdigit() or len(corrected_jan) != 13:
            raise ReviewError("確認済みの13桁JANを入力してください")
    elif action == "ACCEPT_MISSING_EXPIRY" and reason != "EXPIRY_MISSING":
        raise ReviewError("賞味期限欠損だけを確認済みにできます")
    return action, corrected_jan, note


def record_decision(
    report: dict,
    journal_path: Path,
    rules_path: Path,
    issue_id: str,
    payload: dict,
) -> dict:
    issue = next((item for item in report.get("issues", []) if item["issue_id"] == issue_id), None)
    if issue is None:
        raise ReviewError("確認対象が見つかりません")
    action, corrected_jan, note = _validate_decision(issue, payload)
    now = datetime.now(UTC).isoformat()
    decision = {
        "decision_id": str(uuid.uuid4()),
        "analysis_id": report["analysis_id"],
        "issue_id": issue_id,
        "reason": issue["reason"],
        "source_value": issue.get("source_value", ""),
        "action": action,
        "corrected_jan": corrected_jan,
        "note": note,
        "decided_at": now,
        "source": "OPERATOR",
    }
    _append_jsonl(journal_path, decision)
    if bool(payload.get("remember")) and action == "MAP_JAN":
        rule_key = f"{issue['reason']}\0{issue.get('source_value', '')}"
        rule = {
            "rule_id": hashlib.sha256(rule_key.encode("utf-8")).hexdigest()[:24],
            "reason": issue["reason"],
            "source_value": issue.get("source_value", ""),
            "action": action,
            "corrected_jan": corrected_jan,
            "created_at": now,
            "source_decision_id": decision["decision_id"],
        }
        _append_jsonl(rules_path, rule)
        decision["remembered"] = True
    return decision


def apply_remembered_rules(report: dict, journal_path: Path, rules_path: Path) -> int:
    existing = latest_decisions(journal_path)
    rules = {
        (item.get("reason"), item.get("source_value")): item for item in _read_jsonl(rules_path)
    }
    applied = 0
    for issue in report.get("issues", []):
        if issue["issue_id"] in existing:
            continue
        rule = rules.get((issue["reason"], issue.get("source_value")))
        if not rule:
            continue
        record = {
            "decision_id": str(uuid.uuid4()),
            "analysis_id": report["analysis_id"],
            "issue_id": issue["issue_id"],
            "reason": issue["reason"],
            "source_value": issue.get("source_value", ""),
            "action": rule["action"],
            "corrected_jan": rule.get("corrected_jan"),
            "note": "保存済みの担当者判断を適用",
            "decided_at": datetime.now(UTC).isoformat(),
            "source": "REMEMBERED_RULE",
            "rule_id": rule["rule_id"],
        }
        _append_jsonl(journal_path, record)
        applied += 1
    return applied


def rebuild_reviewed_prepared(
    base_path: Path, target_path: Path, report: dict, journal_path: Path
) -> None:
    totals: dict[tuple[str, str, str], Decimal] = {}
    with base_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row["ds"], row["unique_id"].split(":", 1)[0], row["unique_id"].split(":", 1)[1])
            totals[key] = totals.get(key, Decimal()) + Decimal(row["y"])
    decisions = latest_decisions(journal_path)
    for issue in report.get("issues", []):
        decision = decisions.get(issue["issue_id"])
        if not decision or decision.get("action") != "MAP_JAN" or issue["category"] != "shipment":
            continue
        jan = decision["corrected_jan"]
        for occurrence, value in issue.get("occurrence_totals", {}).items():
            center, day = occurrence.split("\0", 1)
            key = (day, center, jan)
            totals[key] = totals.get(key, Decimal()) + Decimal(value)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("ds", "unique_id", "y"))
        for (day, center, jan), quantity in sorted(totals.items()):
            writer.writerow((day, f"{center}:{jan}", str(quantity)))
    temporary.replace(target_path)
