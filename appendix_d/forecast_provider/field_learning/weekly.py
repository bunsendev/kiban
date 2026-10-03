"""Immutable weekly review snapshots built from append-only field evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from ..inventory_foundation.domain import canonical_decimal
from .contracts import LearningCandidateType, OperatorDecision, OperatorReasonCode
from .weekly_domain import build_learning_candidate, build_weekly_review

_REASON_CANDIDATES = {
    OperatorReasonCode.PROMOTION: LearningCandidateType.CALENDAR_FEATURE,
    OperatorReasonCode.SEASONAL_EVENT: LearningCandidateType.CALENDAR_FEATURE,
    OperatorReasonCode.EXPECTED_LARGE_ORDER: LearningCandidateType.LARGE_ORDER_INPUT,
    OperatorReasonCode.PRODUCTION_CONSTRAINT: (
        LearningCandidateType.PRODUCTION_PLAN_INTEGRATION
    ),
    OperatorReasonCode.DELIVERY_CONSTRAINT: LearningCandidateType.ROUTE_POLICY,
    OperatorReasonCode.EXPIRY_CONCERN: LearningCandidateType.EXPIRY_POLICY,
    OperatorReasonCode.DATA_ERROR: LearningCandidateType.DATA_QUALITY,
    OperatorReasonCode.STOCKOUT_CONCERN: LearningCandidateType.STOCKOUT_POLICY,
}


def build_weekly_review_bundle(
    store,
    *,
    week_end: date,
    pilot_scope_versions: tuple[str, ...],
    aggregation_version: str,
    threshold_version: str,
    minimum_evidence_count: int,
    reviewer: str,
    known_at: datetime,
    recorded_at: datetime,
):
    """Build one review and its candidates without changing a model or policy."""

    if isinstance(minimum_evidence_count, bool) or not 1 <= minimum_evidence_count <= 30:
        raise ValueError("minimum_evidence_countは1以上30以下です")
    if known_at.tzinfo is None or known_at.utcoffset() is None:
        raise ValueError("known_atはtimezone付きです")
    scopes = tuple(sorted(set(pilot_scope_versions)))
    week_start = week_end - timedelta(days=6)
    previous_end = week_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=6)
    current = _aggregate(store, week_start, week_end, scopes, known_at)
    previous = _aggregate(store, previous_start, previous_end, scopes, known_at)
    if current["reference_case_count"] == 0:
        raise ValueError("指定した週・Pilot Scopeに比較対象がありません")
    report = {
        "format": "field-weekly-review-report-v1",
        "mode": "SHADOW",
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "pilot_scope_versions": list(scopes),
        "aggregation_version": aggregation_version,
        "threshold": {
            "version": threshold_version,
            "minimum_evidence_count": minimum_evidence_count,
        },
        "current": current,
        "previous": previous,
        "week_over_week": _week_over_week(current, previous),
        "notice": (
            "空欄は未取得であり0ではありません。改善候補は調査対象で、"
            "モデル・特徴量・policyへ自動反映しません。"
        ),
    }
    review = build_weekly_review(
        week_start=week_start,
        week_end=week_end,
        pilot_scope_versions=scopes,
        aggregation_version=aggregation_version,
        threshold_version=threshold_version,
        report=report,
        reviewer=reviewer,
        known_at=known_at,
        recorded_at=recorded_at,
    )
    candidates = tuple(
        build_learning_candidate(
            review_id=review.review_id,
            candidate_type=LearningCandidateType(seed["candidate_type"]),
            evidence_count=seed["evidence_count"],
            impact_quantity=seed["impact_quantity_cases"],
            reason_codes=tuple(seed["reason_codes"]),
            evidence_case_ids=tuple(seed["evidence_case_ids"]),
        )
        for seed in current["candidate_observations"]
        if seed["evidence_count"] >= minimum_evidence_count
    )
    return review, candidates


def _aggregate(store, start: date, end: date, scopes: tuple[str, ...], known_at: datetime) -> dict:
    actual_cutoff = known_at.astimezone(UTC)
    cases = [
        case for case in _cases(store, start, end, scopes)
        if case.known_at <= actual_cutoff
    ]
    forecast_abs = Decimal(0)
    forecast_squared = Decimal(0)
    forecast_bias = Decimal(0)
    actual_demand_total = Decimal(0)
    forecast_coverage = 0
    operator_count = 0
    operator_quantity_count = 0
    operator_change_count = 0
    operator_abs_delta = Decimal(0)
    operator_actual_count = 0
    actual_count = 0
    reasons: dict[str, int] = defaultdict(int)
    operational = {
        "stockout_cases": Decimal(0),
        "expired_cases": Decimal(0),
        "interwarehouse_transfer_cases": Decimal(0),
    }
    operational_days = dict.fromkeys(operational, 0)
    operational_coverage = dict.fromkeys(operational, 0)
    evidence: dict[LearningCandidateType, dict] = {}

    def observe(kind, case_id: str, reason: str, impact: Decimal | None) -> None:
        item = evidence.setdefault(
            kind, {"case_ids": set(), "reason_codes": set(), "impacts": {}},
        )
        item["case_ids"].add(case_id)
        item["reason_codes"].add(reason)
        if impact is not None:
            item["impacts"][case_id] = max(
                item["impacts"].get(case_id, Decimal(0)), abs(impact)
            )

    for case in cases:
        decision = _latest_before(store.list_operator_decisions(case.case_id), actual_cutoff)
        actual = _latest_before(store.list_actual_outcomes(case.case_id), actual_cutoff)
        if decision is not None:
            operator_count += 1
            if decision.operator_quantity is not None:
                operator_quantity_count += 1
                gap = decision.operator_quantity - case.system_reference_quantity
                operator_abs_delta += abs(gap)
            else:
                gap = None
            if decision.operator_decision in {
                OperatorDecision.INCREASED,
                OperatorDecision.DECREASED,
                OperatorDecision.REJECTED,
            }:
                operator_change_count += 1
            if decision.operator_reason_code is not None:
                reason = decision.operator_reason_code
                reasons[reason.value] += 1
                kind = _REASON_CANDIDATES.get(reason)
                if kind is not None:
                    observe(kind, case.case_id, reason.value, gap)
        if actual is None:
            observe(LearningCandidateType.DATA_QUALITY, case.case_id, "ACTUAL_MISSING", None)
            continue
        actual_count += 1
        if actual.actual_demand_quantity is not None:
            error = case.system_forecast_quantity - actual.actual_demand_quantity
            forecast_abs += abs(error)
            forecast_squared += error * error
            forecast_bias += error
            actual_demand_total += actual.actual_demand_quantity
            forecast_coverage += 1
        if (
            decision is not None
            and decision.operator_quantity is not None
            and actual.actual_shipped_quantity is not None
        ):
            operator_actual_count += 1
        for key, value, kind in (
            ("stockout_cases", actual.stockout_quantity, LearningCandidateType.STOCKOUT_POLICY),
            ("expired_cases", actual.expired_quantity, LearningCandidateType.EXPIRY_POLICY),
            (
                "interwarehouse_transfer_cases",
                actual.interwarehouse_transfer_quantity,
                LearningCandidateType.ROUTE_POLICY,
            ),
        ):
            if value is not None:
                operational[key] += value
                operational_coverage[key] += 1
                if value > 0:
                    operational_days[key] += 1
                    observe(kind, case.case_id, key.upper(), value)

    observations = []
    for kind, item in sorted(evidence.items(), key=lambda value: value[0].value):
        case_ids = sorted(item["case_ids"])
        observations.append({
            "candidate_type": kind.value,
            "evidence_count": len(case_ids),
            "impact_quantity_cases": (
                canonical_decimal(sum(item["impacts"].values(), Decimal(0)))
                if item["impacts"] else None
            ),
            "reason_codes": sorted(item["reason_codes"]),
            "evidence_case_ids": case_ids,
        })
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "reference_case_count": len(cases),
        "comparison_coverage": {
            "system_operator": operator_quantity_count,
            "forecast_actual_demand": forecast_coverage,
            "operator_actual_shipped": operator_actual_count,
            "actual_any": actual_count,
            "actual_missing": len(cases) - actual_count,
        },
        "forecast_kpis": {
            "mae_cases": _ratio(forecast_abs, forecast_coverage),
            "rmse_cases": (
                None if forecast_coverage == 0
                else canonical_decimal((forecast_squared / forecast_coverage).sqrt())
            ),
            "wape": _ratio(forecast_abs, actual_demand_total),
            "bias": _ratio(forecast_bias, actual_demand_total),
        },
        "operator_kpis": {
            "decision_count": operator_count,
            "change_count": operator_change_count,
            "change_rate": _ratio(Decimal(operator_change_count), operator_count),
            "absolute_delta_cases": canonical_decimal(operator_abs_delta),
            "reason_counts": [
                {"reason_code": reason, "count": count}
                for reason, count in sorted(
                    reasons.items(), key=lambda value: (-value[1], value[0])
                )
            ],
        },
        "operational_kpis": {
            key: None if operational_coverage[key] == 0 else canonical_decimal(value)
            for key, value in operational.items()
        },
        "operational_days": operational_days,
        "operational_coverage": operational_coverage,
        "candidate_observations": observations,
    }


def _cases(store, start: date, end: date, scopes: tuple[str, ...]):
    values = []
    after = None
    while True:
        page = store.list_reference_cases_page(
            start_date=start, end_date=end, after=after, limit=500,
        )
        values.extend(case for case in page if case.pilot_scope_version in scopes)
        if len(page) < 500:
            return values
        after = (page[-1].business_date, page[-1].case_id)


def _latest_before(events, known_at: datetime):
    available = [event for event in events if event.known_at <= known_at]
    return available[-1] if available else None


def _ratio(numerator: Decimal, denominator) -> str | None:
    denominator = Decimal(denominator)
    if denominator == 0:
        return None
    return canonical_decimal(numerator / denominator)


def _week_over_week(current: dict, previous: dict) -> dict:
    result = {}
    for name in ("mae_cases", "rmse_cases", "wape", "bias"):
        left = current["forecast_kpis"][name]
        right = previous["forecast_kpis"][name]
        result[name] = (
            None if left is None or right is None
            else canonical_decimal(Decimal(left) - Decimal(right))
        )
    for name in (
        "stockout_cases", "expired_cases", "interwarehouse_transfer_cases",
    ):
        left = current["operational_kpis"][name]
        right = previous["operational_kpis"][name]
        result[name] = (
            None if left is None or right is None
            else canonical_decimal(Decimal(left) - Decimal(right))
        )
    return result
