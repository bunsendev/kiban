"""Pure policy evaluation for a runtime-aware Pilot comparison."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from forecast_provider.inventory_foundation.domain import canonical_decimal


def evaluate_pilot_policy(
    runtime_report: dict,
    *,
    candidate_version: str,
    pilot_scope_versions: set[str],
    policy: dict,
) -> dict:
    """Evaluate evidence sufficiency without changing an application state."""
    comparisons = [
        item
        for item in runtime_report.get("pairwise_comparisons", [])
        if item.get("candidate_version") == candidate_version
    ]
    candidate_groups = [
        item
        for item in runtime_report.get("runtime_groups", [])
        if item.get("assignment_status") == "CANDIDATE_SELECTED"
        and item.get("runtime_version") == candidate_version
    ]
    if len(comparisons) != 1 or len(candidate_groups) != 1:
        return {
            "status": "BLOCKED",
            "recommended_action": "PAUSE_PILOT",
            "checks": [
                _check(
                    "UNIQUE_CANDIDATE_EVIDENCE",
                    False,
                    {"comparison_count": len(comparisons), "group_count": len(candidate_groups)},
                    "候補版に対応する比較と集計が各1件",
                )
            ],
        }
    comparison = comparisons[0]
    candidate = candidate_groups[0]
    candidate_scopes = set(candidate.get("pilot_scope_versions") or [])
    start = date.fromisoformat(runtime_report["week_start"])
    end = date.fromisoformat(runtime_report["week_end"])
    days = (end - start).days + 1
    source_count = int(runtime_report.get("source_reference_case_count") or 0)
    unattributed = int(runtime_report.get("unattributed_case_count") or 0)
    unattributed_ratio = None if source_count == 0 else Decimal(unattributed) / source_count
    reference_count = int(candidate.get("reference_case_count") or 0)
    changed = int(candidate.get("operator_kpis", {}).get("change_count") or 0)
    change_ratio = None if reference_count == 0 else Decimal(changed) / reference_count
    delta = comparison.get("candidate_minus_baseline", {})
    business = comparison.get("shared_actual_business_kpis", {})
    coverage = comparison.get("shared_actual_business_coverage", {})
    same_actual = int(comparison.get("same_actual_count") or 0)

    checks = [
        _check(
            "PILOT_SCOPE_MATCH",
            bool(candidate_scopes) and candidate_scopes <= pilot_scope_versions,
            sorted(candidate_scopes),
            sorted(pilot_scope_versions),
        ),
        _check(
            "COMPARISON_READY",
            comparison.get("status") == "READY",
            comparison.get("status"),
            "READY",
        ),
        _check(
            "OBSERVATION_DAYS",
            days >= policy["minimum_observation_days"],
            days,
            policy["minimum_observation_days"],
        ),
        _check(
            "SAME_ACTUAL_COUNT",
            same_actual >= policy["minimum_same_actual_count"],
            same_actual,
            policy["minimum_same_actual_count"],
        ),
        _decimal_check(
            "UNATTRIBUTED_RATIO", unattributed_ratio, policy["maximum_unattributed_ratio"]
        ),
        _decimal_check(
            "MAE_DELTA_CASES", _decimal(delta.get("mae_cases")), policy["maximum_mae_delta_cases"]
        ),
        _decimal_check("WAPE_DELTA", _decimal(delta.get("wape")), policy["maximum_wape_delta"]),
        _decimal_check(
            "OPERATOR_CHANGE_RATIO", change_ratio, policy["maximum_operator_change_ratio"]
        ),
    ]
    for key, maximum in (
        ("stockout_cases", policy["maximum_stockout_cases"]),
        ("expired_cases", policy["maximum_expired_cases"]),
        ("interwarehouse_transfer_cases", policy["maximum_interwarehouse_transfer_cases"]),
    ):
        checks.append(
            _check(
                f"{key.upper()}_COVERAGE",
                int(coverage.get(key) or 0) >= same_actual and same_actual > 0,
                int(coverage.get(key) or 0),
                same_actual,
            )
        )
        checks.append(_decimal_check(key.upper(), _decimal(business.get(key)), maximum))
    failed_codes = {item["code"] for item in checks if not item["passed"]}
    passed = not failed_codes
    if passed:
        action = "FORWARD_TO_ACCEPTANCE"
    elif failed_codes <= {"OBSERVATION_DAYS", "SAME_ACTUAL_COUNT"}:
        action = "CONTINUE_PILOT"
    else:
        action = "REQUEST_ROLLBACK"
    return {
        "status": "PASSED" if passed else "BLOCKED",
        "recommended_action": action,
        "checks": checks,
    }


def _check(code: str, passed: bool, actual, expected) -> dict:
    return {"code": code, "passed": passed, "actual": actual, "expected": expected}


def _decimal_check(code: str, actual: Decimal | None, maximum: Decimal) -> dict:
    return _check(
        code,
        actual is not None and actual <= maximum,
        None if actual is None else canonical_decimal(actual),
        canonical_decimal(maximum),
    )


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
