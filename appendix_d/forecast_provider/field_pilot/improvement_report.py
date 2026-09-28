"""既存の現場検証台帳をJAN×倉庫×業務日で照合する管理者向け集計。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal


def weekly_field_report(field_store, end_date: date, *, minimum_gap_cases: Decimal,
                        repeat_days: int, threshold_version: str) -> dict:
    if (not minimum_gap_cases.is_finite() or minimum_gap_cases < 0
            or isinstance(repeat_days, bool) or not 2 <= repeat_days <= 30
            or not threshold_version.strip()):
        raise ValueError("IMPROVEMENT_THRESHOLD_INVALID")
    start_date = end_date - timedelta(days=6)
    cases = []
    after = None
    while True:
        page = field_store.list_reference_cases_page(
            start_date=start_date, end_date=end_date, after=after, limit=500,
        )
        cases.extend(page)
        if len(page) < 500:
            break
        after = (page[-1].business_date, page[-1].case_id)
    by_key = defaultdict(list)
    case_comparisons = []
    totals = {"stockout_cases": Decimal(0), "expired_cases": Decimal(0),
              "interwarehouse_transfer_cases": Decimal(0)}
    coverage = dict.fromkeys(totals, 0)
    for case in cases:
        decisions = field_store.list_operator_decisions(case.case_id)
        actuals = field_store.list_actual_outcomes(case.case_id)
        decision = decisions[-1] if decisions else None
        actual = actuals[-1] if actuals else None
        key = (case.jan, case.warehouse_id)
        gap = None if decision is None or decision.operator_quantity is None else (
            decision.operator_quantity - case.system_reference_quantity
        )
        comparisons = {
            "system_vs_operator_cases": None if gap is None else str(gap),
            "forecast_vs_actual_demand_cases": (
                None if actual is None or actual.actual_demand_quantity is None
                else str(actual.actual_demand_quantity - case.system_forecast_quantity)
            ),
            "operator_vs_actual_shipped_cases": (
                None if actual is None or decision is None or decision.operator_quantity is None
                or actual.actual_shipped_quantity is None
                else str(actual.actual_shipped_quantity - decision.operator_quantity)
            ),
        }
        case_comparisons.append({
            "case_id": case.case_id, "business_date": case.business_date.isoformat(),
            "jan": case.jan, "warehouse_id": case.warehouse_id,
            "comparisons": comparisons,
        })
        if gap is not None and abs(gap) >= minimum_gap_cases and gap != 0:
            by_key[key].append({
                "business_date": case.business_date.isoformat(),
                "case_id": case.case_id, "gap_cases": str(gap),
                "comparisons": comparisons,
                "actual_available": actual is not None,
            })
        if actual is not None:
            for name, value in (
                ("stockout_cases", actual.stockout_quantity),
                ("expired_cases", actual.expired_quantity),
                ("interwarehouse_transfer_cases", actual.interwarehouse_transfer_quantity),
            ):
                if value is not None:
                    totals[name] += value
                    coverage[name] += 1
    candidates = []
    for (jan, warehouse_id), entries in sorted(by_key.items()):
        unique_days = len({item["business_date"] for item in entries})
        candidates.append({
            "jan": jan, "warehouse_id": warehouse_id,
            "state": ("QUESTION_READY" if unique_days >= repeat_days else
                      "REPEATED" if unique_days >= 2 else "OBSERVED"),
            "observed_days": unique_days, "entries": entries,
            "interpretation": "担当者判断と参考値の差。原因・改善効果は未確定。",
        })
    return {
        "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
        "reference_case_count": len(cases),
        "complete": True,
        "threshold": {"version": threshold_version,
                      "minimum_gap_cases": str(minimum_gap_cases),
                      "repeat_days": repeat_days},
        "business_kpis": {
            key: None if coverage[key] == 0 else str(value)
            for key, value in totals.items()
        },
        "kpi_coverage": coverage,
        "case_comparisons": case_comparisons,
        "candidates": candidates,
        "note": "空欄の業務KPIは未取得です。差異から因果関係を推定しません。",
    }
