"""Append-only operator review ledger for Portable shipment recommendations."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from forecast_provider.field_learning import OperatorDecision, OperatorReasonCode
from forecast_provider.inventory_foundation.domain import canonical_decimal

from .formal_shipment_daily import canonical_json
from .production_handoff import ProductionHandoffError


class DecisionReviewConflict(ProductionHandoffError):
    """Raised when an operator submits an outdated review revision."""


class PortableDecisionReviews:
    """Keep SHADOW recommendations and human judgements separate and auditable."""

    def __init__(self, database: Path) -> None:
        self.database = database
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS shipment_decision_reviews (
                    review_id TEXT PRIMARY KEY,
                    request_key TEXT NOT NULL,
                    result_sha256 TEXT NOT NULL,
                    jan TEXT NOT NULL,
                    warehouse_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    operator_decision TEXT NOT NULL,
                    system_quantity_cases TEXT NOT NULL,
                    operator_quantity_cases TEXT,
                    delta_cases TEXT,
                    reason_code TEXT,
                    comment TEXT,
                    actor TEXT NOT NULL,
                    known_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    UNIQUE(request_key, jan, warehouse_id, revision)
                );
                CREATE INDEX IF NOT EXISTS ix_shipment_decision_reviews_request
                    ON shipment_decision_reviews(request_key, jan, warehouse_id, revision);
                """
            )

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def record(self, result: dict, payload: dict) -> dict:
        request_key = str(result["request_key"])
        row = _recommendation(result, payload)
        expected = payload.get("expected_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ProductionHandoffError("expected_revisionは0以上の整数です")
        values = _review_values(row, payload)
        revision = expected + 1
        now = datetime.now(UTC).isoformat()
        immutable = {
            "format": "portable-shipment-decision-review-v1",
            "request_key": request_key,
            "result_sha256": result["result_sha256"],
            "jan": row["jan"],
            "warehouse_id": row["warehouse_id"],
            "revision": revision,
            **values,
            "known_at": now,
            "recorded_at": now,
        }
        content_sha = hashlib.sha256(canonical_json(immutable)).hexdigest()
        review_id = f"shipment-review-{content_sha}"
        record = {
            "review_id": review_id,
            **immutable,
            "content_sha256": content_sha,
        }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = db.execute(
                "SELECT * FROM shipment_decision_reviews WHERE request_key=? AND jan=? "
                "AND warehouse_id=? ORDER BY revision DESC LIMIT 1",
                (request_key, row["jan"], row["warehouse_id"]),
            ).fetchone()
            current = 0 if latest is None else int(latest["revision"])
            if current != expected:
                if current == revision and _same_review(latest, result, values, revision):
                    return _row(latest)
                raise DecisionReviewConflict(
                    "別の判断が先に保存されました。表示を更新してから再入力してください"
                )
            db.execute(
                """INSERT INTO shipment_decision_reviews(
                    review_id, request_key, result_sha256, jan, warehouse_id, revision,
                    operator_decision, system_quantity_cases, operator_quantity_cases,
                    delta_cases, reason_code, comment, actor, known_at, recorded_at,
                    content_sha256
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    review_id,
                    request_key,
                    result["result_sha256"],
                    row["jan"],
                    row["warehouse_id"],
                    revision,
                    values["operator_decision"],
                    values["system_quantity_cases"],
                    values["operator_quantity_cases"],
                    values["delta_cases"],
                    values["reason_code"],
                    values["comment"],
                    values["actor"],
                    now,
                    now,
                    content_sha,
                ),
            )
        return record

    def view(self, result: dict) -> dict:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM shipment_decision_reviews WHERE request_key=? "
                "ORDER BY jan, warehouse_id, revision",
                (result["request_key"],),
            ).fetchall()
        history = [_row(row) for row in rows]
        if any(item["result_sha256"] != result["result_sha256"] for item in history):
            raise ProductionHandoffError("担当者判断履歴と試算結果の整合性を確認できません")
        latest = {}
        for item in history:
            latest[f"{item['jan']}::{item['warehouse_id']}"] = item
        return {
            "request_key": result["request_key"],
            "result_sha256": result["result_sha256"],
            "mode": "SHADOW",
            "latest": latest,
            "history": history,
            "improvement_candidates": _improvement_candidates(history),
            "notice": "担当者判断は設定改善候補です。予測・policyへ自動反映しません。",
        }


def _recommendation(result: dict, payload: dict) -> dict:
    jan = str(payload.get("jan") or "").strip()
    warehouse = str(payload.get("warehouse_id") or "").strip()
    for row in result.get("recommendations", []):
        if row.get("jan") == jan and row.get("warehouse_id") == warehouse:
            return row
    raise ProductionHandoffError("対象の商品・倉庫が試算結果にありません")


def _review_values(row: dict, payload: dict) -> dict:
    if payload.get("confirm_shadow_review") is not True:
        raise ProductionHandoffError("SHADOW参考値であることを確認してください")
    actor = str(payload.get("actor") or "").strip()
    if not actor or len(actor) > 100:
        raise ProductionHandoffError("確認者は1〜100文字です")
    try:
        decision = OperatorDecision(str(payload.get("operator_decision") or ""))
    except ValueError as exc:
        raise ProductionHandoffError("担当者判断を確認してください") from exc
    reason_raw = str(payload.get("reason_code") or "").strip()
    try:
        reason = None if not reason_raw else OperatorReasonCode(reason_raw)
    except ValueError as exc:
        raise ProductionHandoffError("判断理由を確認してください") from exc
    comment = str(payload.get("comment") or "").strip() or None
    if comment is not None and len(comment) > 500:
        raise ProductionHandoffError("補足は500文字以下です")
    system = _quantity(row["recommended_shipment_cases"], "推奨出荷量", required=True)
    operator = _quantity(payload.get("operator_quantity_cases"), "判断後数量")
    if decision is OperatorDecision.ACCEPTED:
        if operator is None:
            operator = system
        if operator != system:
            raise ProductionHandoffError("採用時の数量は推奨出荷量と一致させてください")
    elif decision is OperatorDecision.INCREASED:
        if operator is None or operator <= system:
            raise ProductionHandoffError("増量時は推奨出荷量より大きい数量が必要です")
    elif decision is OperatorDecision.DECREASED:
        if operator is None or operator >= system:
            raise ProductionHandoffError("減量時は推奨出荷量より小さい数量が必要です")
    elif decision is OperatorDecision.REJECTED:
        operator = None
    elif decision is OperatorDecision.NO_ACTION:
        operator = Decimal("0")
    if decision in {
        OperatorDecision.INCREASED,
        OperatorDecision.DECREASED,
        OperatorDecision.REJECTED,
    } and reason is None:
        raise ProductionHandoffError("増減・見送りには判断理由が必要です")
    if reason is OperatorReasonCode.OTHER and comment is None:
        raise ProductionHandoffError("その他の理由には補足が必要です")
    delta = None if operator is None else operator - system
    return {
        "operator_decision": decision.value,
        "system_quantity_cases": canonical_decimal(system),
        "operator_quantity_cases": None if operator is None else canonical_decimal(operator),
        "delta_cases": None if delta is None else canonical_decimal(delta),
        "reason_code": None if reason is None else reason.value,
        "comment": comment,
        "actor": actor,
    }


def _quantity(value, label: str, *, required: bool = False) -> Decimal | None:
    if value in (None, ""):
        if required:
            raise ProductionHandoffError(f"{label}は必須です")
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProductionHandoffError(f"{label}は数値です") from exc
    if not result.is_finite() or result < 0:
        raise ProductionHandoffError(f"{label}は0以上の有限値です")
    return result


def _row(row: sqlite3.Row) -> dict:
    value = {"format": "portable-shipment-decision-review-v1", **dict(row)}
    immutable = {
        key: value[key]
        for key in (
            "format",
            "request_key",
            "result_sha256",
            "jan",
            "warehouse_id",
            "revision",
            "operator_decision",
            "system_quantity_cases",
            "operator_quantity_cases",
            "delta_cases",
            "reason_code",
            "comment",
            "actor",
            "known_at",
            "recorded_at",
        )
    }
    expected = hashlib.sha256(canonical_json(immutable)).hexdigest()
    if value["content_sha256"] != expected:
        raise ProductionHandoffError("担当者判断履歴の整合性を確認できません")
    return value


def _same_review(row: sqlite3.Row, result: dict, values: dict, revision: int) -> bool:
    expected = {
        "result_sha256": result["result_sha256"],
        "revision": revision,
        **values,
    }
    return all(row[key] == value for key, value in expected.items())


def _improvement_candidates(history: list[dict]) -> list[dict]:
    latest = {}
    for item in history:
        latest[(item["jan"], item["warehouse_id"])] = item
    groups: dict[tuple[str, str], list[dict]] = {}
    for item in latest.values():
        if item["operator_decision"] not in {
            OperatorDecision.INCREASED.value,
            OperatorDecision.DECREASED.value,
            OperatorDecision.REJECTED.value,
        }:
            continue
        key = (item["operator_decision"], item["reason_code"] or "UNSPECIFIED")
        groups.setdefault(key, []).append(item)
    result = []
    for (decision, reason), items in sorted(groups.items()):
        deltas = [Decimal(item["delta_cases"]) for item in items if item["delta_cases"] is not None]
        result.append({
            "operator_decision": decision,
            "reason_code": reason,
            "count": len(items),
            "average_delta_cases": None
            if not deltas
            else canonical_decimal(sum(deltas, Decimal("0")) / len(deltas)),
            "targets": [
                {"jan": item["jan"], "warehouse_id": item["warehouse_id"]}
                for item in items
            ],
            "automatic_application": False,
        })
    return result
