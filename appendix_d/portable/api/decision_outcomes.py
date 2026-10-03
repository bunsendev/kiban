"""Portable adapter for actual outcomes observed after SHADOW shipment decisions."""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from forecast_provider.field_actuals import FieldActualImporter
from forecast_provider.field_actuals.importer import COLUMNS
from forecast_provider.field_learning import (
    FieldLearningConflict,
    FieldMode,
    SqliteFieldLearningStore,
    build_reference_case,
)
from forecast_provider.inventory_foundation.domain import canonical_decimal

from .formal_shipment_daily import canonical_json
from .production_handoff import ProductionHandoffError


class PortableDecisionOutcomes:
    """Keep post-decision facts separate from recommendations and operator reviews."""

    def __init__(self, database: Path, reviews) -> None:
        self.store = SqliteFieldLearningStore(database)
        self.importer = FieldActualImporter(self.store)
        self.reviews = reviews

    def template(self, result: dict, summary: dict) -> bytes:
        cases = self._cases(result, summary)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(COLUMNS)
        for case in cases:
            actuals = self.store.list_actual_outcomes(case.case_id)
            writer.writerow((case.case_id, len(actuals), "CASE", "", "", "", "", ""))
        return stream.getvalue().encode("utf-8-sig")

    def record(self, result: dict, summary: dict, payload: dict) -> dict:
        allowed = {case.case_id for case in self._cases(result, summary)}
        if payload.get("confirm_actual_outcomes") is not True:
            raise ProductionHandoffError("後日実績が確認済みであることを選択してください")
        source_version = str(payload.get("source_version") or "").strip()
        if not source_version or len(source_version) > 100:
            raise ProductionHandoffError("実績データ版は1〜100文字です")
        known_at = _datetime(payload.get("known_at"), "実績判明日時")
        content = _base64(payload.get("csv_base64"))
        recorded_at = datetime.now(UTC)
        try:
            plan = self.importer.prepare(
                content,
                source_version=source_version,
                known_at=known_at,
                recorded_at=recorded_at,
            )
            if any(event.case_id not in allowed for event in plan.events):
                raise ProductionHandoffError("別の推奨試算に属するcase_idは取り込めません")
            self.importer.apply(plan)
        except FieldLearningConflict as exc:
            raise OutcomeConflict(str(exc)) from exc
        except ValueError as exc:
            if not self._same_import(content, source_version, known_at, allowed):
                raise ProductionHandoffError(str(exc)) from exc
        return self.view(result, summary)

    def view(self, result: dict, summary: dict) -> dict:
        cases = self._cases(result, summary)
        latest_reviews = self.reviews.view(result)["latest"]
        recommendation_by_pair = {
            (row["jan"], row["warehouse_id"]): row for row in result.get("recommendations", [])
        }
        rows = []
        totals = {
            "stockout_cases": Decimal("0"),
            "expired_cases": Decimal("0"),
            "interwarehouse_transfer_cases": Decimal("0"),
        }
        coverage = dict.fromkeys(totals, 0)
        demand_absolute_error = Decimal("0")
        demand_actual_total = Decimal("0")
        demand_bias = Decimal("0")
        demand_coverage = 0
        for case in cases:
            pair = (case.jan, case.warehouse_id)
            recommendation = recommendation_by_pair[pair]
            review = latest_reviews.get(f"{case.jan}::{case.warehouse_id}")
            actuals = self.store.list_actual_outcomes(case.case_id)
            actual = actuals[-1] if actuals else None
            operator_quantity = None if review is None else review["operator_quantity_cases"]
            actual_demand = None if actual is None else actual.actual_demand_quantity
            if actual_demand is not None:
                error = actual_demand - case.system_forecast_quantity
                demand_absolute_error += abs(error)
                demand_bias += case.system_forecast_quantity - actual_demand
                demand_actual_total += actual_demand
                demand_coverage += 1
            if actual is not None:
                for key, value in (
                    ("stockout_cases", actual.stockout_quantity),
                    ("expired_cases", actual.expired_quantity),
                    ("interwarehouse_transfer_cases", actual.interwarehouse_transfer_quantity),
                ):
                    if value is not None:
                        totals[key] += value
                        coverage[key] += 1
            rows.append(
                {
                    "case_id": case.case_id,
                    "business_date": case.business_date.isoformat(),
                    "jan": case.jan,
                    "warehouse_id": case.warehouse_id,
                    "arrival_at": recommendation["arrival_at"],
                    "system_forecast_arrival_demand_cases": canonical_decimal(
                        case.system_forecast_quantity
                    ),
                    "system_recommended_shipment_cases": canonical_decimal(
                        case.system_reference_quantity
                    ),
                    "operator_decision": None if review is None else review["operator_decision"],
                    "operator_quantity_cases": operator_quantity,
                    "actual_revision": 0 if actual is None else actual.revision,
                    "actual_source_version": None if actual is None else actual.source_version,
                    "actual_shipped_cases": _decimal(actual, "actual_shipped_quantity"),
                    "actual_demand_until_arrival_cases": _decimal(actual, "actual_demand_quantity"),
                    "stockout_cases": _decimal(actual, "stockout_quantity"),
                    "expired_cases": _decimal(actual, "expired_quantity"),
                    "interwarehouse_transfer_cases": _decimal(
                        actual, "interwarehouse_transfer_quantity"
                    ),
                    "system_vs_operator_cases": _difference(
                        operator_quantity, case.system_reference_quantity
                    ),
                    "forecast_vs_actual_demand_cases": _difference(
                        None if actual_demand is None else actual_demand,
                        case.system_forecast_quantity,
                    ),
                    "system_vs_actual_shipped_cases": _difference(
                        None if actual is None else actual.actual_shipped_quantity,
                        case.system_reference_quantity,
                    ),
                    "operator_vs_actual_shipped_cases": _difference(
                        None if actual is None else actual.actual_shipped_quantity,
                        operator_quantity,
                    ),
                }
            )
        return {
            "format": "portable-shipment-outcome-comparison-v1",
            "request_key": result["request_key"],
            "result_sha256": result["result_sha256"],
            "mode": "SHADOW",
            "case_count": len(rows),
            "actual_count": sum(item["actual_revision"] > 0 for item in rows),
            "missing_actual_count": sum(item["actual_revision"] == 0 for item in rows),
            "rows": rows,
            "forecast_metrics": {
                "actual_demand_coverage": demand_coverage,
                "mae_cases": (
                    None
                    if demand_coverage == 0
                    else canonical_decimal(demand_absolute_error / demand_coverage)
                ),
                "wape": (
                    None
                    if demand_actual_total == 0
                    else canonical_decimal(demand_absolute_error / demand_actual_total)
                ),
                "bias": (
                    None
                    if demand_actual_total == 0
                    else canonical_decimal(demand_bias / demand_actual_total)
                ),
            },
            "business_kpis": {
                key: None if coverage[key] == 0 else canonical_decimal(value)
                for key, value in totals.items()
            },
            "kpi_coverage": coverage,
            "notice": (
                "空欄は未取得です。0とは扱いません。比較結果から因果関係やpolicy変更を"
                "自動決定しません。"
            ),
        }

    def _cases(self, result: dict, summary: dict):
        if result.get("daily_summary_sha256") != summary.get("summary_sha256"):
            raise ProductionHandoffError("出荷推奨結果と日次サマリーが一致しません")
        calculation_at = _datetime(result.get("calculation_at"), "計算日時")
        warehouses = {item["warehouse_id"]: item for item in summary.get("warehouses", [])}
        policy_payload = {
            "route": result.get("input_versions", {}).get("route_policy_versions", []),
            "safety": result.get("input_versions", {}).get("safety_stock_policy_versions", []),
        }
        policy_version = (
            "portable-shipment-policy-"
            + hashlib.sha256(canonical_json(policy_payload)).hexdigest()[:20]
        )
        recorded_at = max(datetime.now(UTC), calculation_at.astimezone(UTC))
        cases = []
        for row in result.get("recommendations", []):
            warehouse = warehouses.get(row["warehouse_id"])
            if warehouse is None:
                raise ProductionHandoffError("倉庫の正式参照情報が見つかりません")
            try:
                case = build_reference_case(
                    business_date=calculation_at.date(),
                    jan=row["jan"],
                    canonical_product_id=row["jan"],
                    warehouse_id=row["warehouse_id"],
                    forecast_center_id=(warehouse.get("source_center") or row["warehouse_id"]),
                    forecast_run_id=summary["forecast_run_id"],
                    inventory_snapshot_id=warehouse["inventory_snapshot_id"],
                    pilot_scope_version=warehouse["pilot_scope_version"],
                    identity_bridge_version=summary["identity_bridge_version"],
                    system_forecast_quantity=row["arrival_demand_cases"],
                    system_reference_quantity=row["recommended_shipment_cases"],
                    policy_version=policy_version,
                    mode=FieldMode.SHADOW,
                    known_at=calculation_at,
                    recorded_at=recorded_at,
                )
                cases.append(self.store.put_reference_case(case))
            except (KeyError, TypeError, ValueError) as exc:
                raise ProductionHandoffError(str(exc)) from exc
        return sorted(cases, key=lambda item: (item.warehouse_id, item.jan))

    def _same_import(
        self,
        content: bytes,
        source_version: str,
        known_at: datetime,
        allowed: set[str],
    ) -> bool:
        try:
            reader = csv.DictReader(
                io.StringIO(content.decode("utf-8-sig", errors="strict"), newline=""),
                strict=True,
            )
            if reader.fieldnames != list(COLUMNS):
                return False
            rows = list(reader)
        except (UnicodeError, csv.Error):
            return False
        digest = hashlib.sha256(content).hexdigest()
        if not rows:
            return False
        for row in rows:
            case_id = str(row.get("case_id") or "").strip()
            if case_id not in allowed:
                return False
            actuals = self.store.list_actual_outcomes(case_id)
            if not actuals:
                return False
            latest = actuals[-1]
            if (
                latest.source_sha256 != digest
                or latest.source_version != source_version
                or latest.known_at != known_at.astimezone(UTC)
            ):
                return False
        return True


class OutcomeConflict(ProductionHandoffError):
    """Raised when an actual-outcome revision changed concurrently."""


def _datetime(value, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductionHandoffError(f"{label}はtimezone付きISO日時です") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ProductionHandoffError(f"{label}はtimezone付きISO日時です")
    return result


def _base64(value) -> bytes:
    if not isinstance(value, str) or not value:
        raise ProductionHandoffError("後日実績CSVを指定してください")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProductionHandoffError("後日実績CSVを読み取れません") from exc


def _decimal(actual, name: str) -> str | None:
    if actual is None:
        return None
    value = getattr(actual, name)
    return None if value is None else canonical_decimal(value)


def _difference(left, right) -> str | None:
    if left is None or right is None:
        return None
    return canonical_decimal(Decimal(str(left)) - Decimal(str(right)))
