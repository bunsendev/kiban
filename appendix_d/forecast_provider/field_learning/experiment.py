"""Deterministic baseline/challenger comparisons over one fixed case set."""

from __future__ import annotations

from decimal import Decimal

from ..inventory_foundation.domain import canonical_decimal
from .contracts import LearningExperimentTarget


def build_experiment_report(store, plan, challenger_by_case: dict[str, Decimal], *, known_at):
    expected = set(plan.evidence_case_ids)
    extras = sorted(set(challenger_by_case) - expected)
    if extras:
        raise ValueError("調査計画にないcase_idが含まれています")
    rows = []
    observed = {name: [] for name in ("stockout", "expired", "transfer")}
    for case_id in plan.evidence_case_ids:
        case = store.get_reference_case(case_id)
        if case is None or case.known_at > plan.known_at:
            raise ValueError("固定した比較対象caseを確認できません")
        actual_events = [
            value for value in store.list_actual_outcomes(case_id)
            if value.known_at <= known_at
        ]
        actual_event = actual_events[-1] if actual_events else None
        if plan.target is LearningExperimentTarget.DEMAND_FORECAST:
            baseline = case.system_forecast_quantity
            actual = None if actual_event is None else actual_event.actual_demand_quantity
        else:
            baseline = case.system_reference_quantity
            actual = None if actual_event is None else actual_event.actual_shipped_quantity
        challenger = challenger_by_case.get(case_id)
        row = {
            "case_id": case_id,
            "business_date": case.business_date.isoformat(),
            "jan": case.jan,
            "warehouse_id": case.warehouse_id,
            "baseline_quantity": canonical_decimal(baseline),
            "challenger_quantity": _optional(challenger),
            "actual_quantity": _optional(actual),
        }
        if challenger is not None and actual is not None:
            baseline_error = abs(baseline - actual)
            challenger_error = abs(challenger - actual)
            row.update({
                "baseline_absolute_error": canonical_decimal(baseline_error),
                "challenger_absolute_error": canonical_decimal(challenger_error),
                "absolute_error_delta": canonical_decimal(challenger_error - baseline_error),
            })
        else:
            row.update({
                "baseline_absolute_error": None,
                "challenger_absolute_error": None,
                "absolute_error_delta": None,
            })
        rows.append(row)
        if actual_event is not None:
            for key, value in (
                ("stockout", actual_event.stockout_quantity),
                ("expired", actual_event.expired_quantity),
                ("transfer", actual_event.interwarehouse_transfer_quantity),
            ):
                if value is not None:
                    observed[key].append(value)
    comparable = [
        row for row in rows
        if row["actual_quantity"] is not None and row["challenger_quantity"] is not None
    ]
    baseline_pairs = [
        (Decimal(row["baseline_quantity"]), Decimal(row["actual_quantity"]))
        for row in comparable
    ]
    challenger_pairs = [
        (Decimal(row["challenger_quantity"]), Decimal(row["actual_quantity"]))
        for row in comparable
    ]
    baseline_metrics = _metrics(baseline_pairs)
    challenger_metrics = _metrics(challenger_pairs)
    metric_deltas = {
        key: _difference(challenger_metrics[key], baseline_metrics[key])
        for key in ("mae_cases", "rmse_cases", "wape", "bias_cases")
    }
    risk_deltas = {
        key: _difference(challenger_metrics[key], baseline_metrics[key])
        for key in ("underestimate_cases", "overestimate_cases")
    }
    return {
        "format": "field-learning-experiment-report-v1",
        "target": plan.target.value,
        "case_set_sha256": _case_set_digest(plan.evidence_case_ids),
        "coverage": {
            "planned_count": len(rows),
            "challenger_count": sum(row["challenger_quantity"] is not None for row in rows),
            "actual_count": sum(row["actual_quantity"] is not None for row in rows),
            "comparable_count": len(comparable),
            "missing_challenger_case_ids": [
                row["case_id"] for row in rows if row["challenger_quantity"] is None
            ],
            "missing_actual_case_ids": [
                row["case_id"] for row in rows if row["actual_quantity"] is None
            ],
        },
        "baseline": baseline_metrics,
        "challenger": challenger_metrics,
        "delta_challenger_minus_baseline": metric_deltas,
        "quantity_gap_proxies": {
            "baseline": {
                "under_supply_cases": baseline_metrics["underestimate_cases"],
                "excess_supply_cases": baseline_metrics["overestimate_cases"],
            },
            "challenger": {
                "under_supply_cases": challenger_metrics["underestimate_cases"],
                "excess_supply_cases": challenger_metrics["overestimate_cases"],
            },
            "delta_challenger_minus_baseline": {
                "under_supply_cases": risk_deltas["underestimate_cases"],
                "excess_supply_cases": risk_deltas["overestimate_cases"],
            },
            "notice": "数量差の代理指標です。欠品・廃棄の発生量とはみなしません。",
        },
        "comparison": {
            "challenger_better_count": sum(
                Decimal(row["absolute_error_delta"]) < 0 for row in comparable
            ),
            "same_count": sum(Decimal(row["absolute_error_delta"]) == 0 for row in comparable),
            "challenger_worse_count": sum(
                Decimal(row["absolute_error_delta"]) > 0 for row in comparable
            ),
        },
        "observed_business_outcomes": {
            "stockout_cases": _sum_or_none(observed["stockout"]),
            "stockout_coverage": len(observed["stockout"]),
            "expired_cases": _sum_or_none(observed["expired"]),
            "expired_coverage": len(observed["expired"]),
            "interwarehouse_transfer_cases": _sum_or_none(observed["transfer"]),
            "interwarehouse_transfer_coverage": len(observed["transfer"]),
            "notice": "業務Outcomeは観測事実です。Challenger適用時の反実仮想差は推測しません。",
        },
        "rows": rows,
    }


def _metrics(pairs: list[tuple[Decimal, Decimal]]) -> dict:
    if not pairs:
        return {
            "mae_cases": None, "rmse_cases": None, "wape": None,
            "bias_cases": None, "underestimate_cases": None, "overestimate_cases": None,
        }
    errors = [prediction - actual for prediction, actual in pairs]
    absolute = [abs(value) for value in errors]
    count = Decimal(len(pairs))
    actual_total = sum((abs(actual) for _, actual in pairs), Decimal(0))
    return {
        "mae_cases": canonical_decimal(sum(absolute, Decimal(0)) / count),
        "rmse_cases": canonical_decimal(
            (sum((value * value for value in errors), Decimal(0)) / count).sqrt()
        ),
        "wape": (
            None if actual_total == 0
            else canonical_decimal(sum(absolute, Decimal(0)) / actual_total)
        ),
        "bias_cases": canonical_decimal(sum(errors, Decimal(0)) / count),
        "underestimate_cases": canonical_decimal(
            sum((-value for value in errors if value < 0), Decimal(0))
        ),
        "overestimate_cases": canonical_decimal(
            sum((value for value in errors if value > 0), Decimal(0))
        ),
    }


def _difference(left: str | None, right: str | None) -> str | None:
    if left is None or right is None:
        return None
    return canonical_decimal(Decimal(left) - Decimal(right))


def _optional(value: Decimal | None) -> str | None:
    return None if value is None else canonical_decimal(value)


def _sum_or_none(values: list[Decimal]) -> str | None:
    return None if not values else canonical_decimal(sum(values, Decimal(0)))


def _case_set_digest(case_ids: tuple[str, ...]) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(case_ids, separators=(",", ":")).encode()).hexdigest()
