"""Pure aggregation for runtime-aware weekly evaluations."""

from decimal import Decimal

from forecast_provider.inventory_foundation.domain import canonical_decimal


def aggregate_runtime_group(signature: tuple, items: list[dict]) -> dict:
    version, configuration_sha, provider, model, status = signature
    actual_rows = [item for item in items if item["actual"] is not None]
    demand_rows = [
        item for item in actual_rows if item["actual"].actual_demand_quantity is not None
    ]
    errors = [
        item["case"].system_forecast_quantity - item["actual"].actual_demand_quantity
        for item in demand_rows
    ]
    demand_total = sum(
        (item["actual"].actual_demand_quantity for item in demand_rows), Decimal(0)
    )
    operational, coverage = _operational(actual_rows)
    decisions = [item for item in items if item["decision"] is not None]
    changed = [
        item for item in decisions
        if item["decision"].operator_quantity is not None
        and item["decision"].operator_quantity != item["case"].system_reference_quantity
    ]
    return {
        "runtime_version": version,
        "runtime_configuration_sha256": configuration_sha,
        "provider_id": provider,
        "model_name": model,
        "assignment_status": status,
        "pilot_scope_versions": sorted({item["case"].pilot_scope_version for item in items}),
        "forecast_run_ids": sorted({item["case"].forecast_run_id for item in items}),
        "reference_case_count": len(items),
        "actual_count": len(actual_rows),
        "missing_actual_count": len(items) - len(actual_rows),
        "forecast_kpis": _forecast_metrics(errors, demand_total),
        "operator_kpis": {
            "decision_count": len(decisions),
            "change_count": len(changed),
            "absolute_delta_cases": canonical_decimal(sum((
                abs(item["decision"].operator_quantity - item["case"].system_reference_quantity)
                for item in changed
            ), Decimal(0))),
        },
        "operational_kpis": operational,
        "operational_coverage": coverage,
    }


def pairwise_runtime_comparisons(groups: dict) -> list[dict]:
    baselines = [item for item in groups.items() if item[0][4] == "BASELINE_SELECTED"]
    candidates = [item for item in groups.items() if item[0][4] == "CANDIDATE_SELECTED"]
    result = []
    for baseline_signature, baseline_items in baselines:
        for candidate_signature, candidate_items in candidates:
            result.append(_compare_pair(
                baseline_signature, baseline_items,
                candidate_signature, candidate_items,
            ))
    return result


def _compare_pair(baseline_signature, baseline_items, candidate_signature, candidate_items):
    baseline, baseline_duplicates = _index_cases(baseline_items)
    candidate, candidate_duplicates = _index_cases(candidate_items)
    duplicate_keys = sorted(baseline_duplicates | candidate_duplicates)
    common = sorted(set(baseline) & set(candidate))
    matched = []
    mismatched = []
    for key in common:
        left = baseline[key]
        right = candidate[key]
        if _actual_signature(left["actual"]) != _actual_signature(right["actual"]):
            mismatched.append(key)
        elif left["actual"] is not None:
            matched.append((left, right))
    demand = [
        pair for pair in matched if pair[0]["actual"].actual_demand_quantity is not None
    ]
    baseline_errors = [
        left["case"].system_forecast_quantity - left["actual"].actual_demand_quantity
        for left, _ in demand
    ]
    candidate_errors = [
        right["case"].system_forecast_quantity - right["actual"].actual_demand_quantity
        for _, right in demand
    ]
    actual_total = sum(
        (left["actual"].actual_demand_quantity for left, _ in demand), Decimal(0)
    )
    left_metrics = _forecast_metrics(baseline_errors, actual_total)
    right_metrics = _forecast_metrics(candidate_errors, actual_total)
    shared_operational, shared_coverage = _operational([left for left, _ in matched])
    status = "READY"
    if duplicate_keys:
        status = "BLOCKED_DUPLICATE_CASE"
    elif mismatched:
        status = "BLOCKED_ACTUAL_MISMATCH"
    elif not demand:
        status = "INSUFFICIENT_COMMON_ACTUAL"
    return {
        "baseline_version": baseline_signature[0],
        "baseline_configuration_sha256": baseline_signature[1],
        "candidate_version": candidate_signature[0],
        "candidate_configuration_sha256": candidate_signature[1],
        "status": status,
        "common_case_count": len(common),
        "same_actual_count": len(matched),
        "forecast_actual_coverage": len(demand),
        "actual_mismatch_count": len(mismatched),
        "duplicate_case_count": len(duplicate_keys),
        "baseline_forecast_kpis": left_metrics,
        "candidate_forecast_kpis": right_metrics,
        "candidate_minus_baseline": {
            key: _metric_delta(right_metrics[key], left_metrics[key])
            for key in ("mae_cases", "rmse_cases", "wape", "bias")
        },
        "shared_actual_business_kpis": shared_operational,
        "shared_actual_business_coverage": shared_coverage,
    }


def _forecast_metrics(errors: list[Decimal], actual_total: Decimal) -> dict:
    count = len(errors)
    absolute = sum((abs(value) for value in errors), Decimal(0))
    squared = sum((value * value for value in errors), Decimal(0))
    bias = sum(errors, Decimal(0))
    return {
        "actual_demand_coverage": count,
        "mae_cases": None if not count else canonical_decimal(absolute / count),
        "rmse_cases": None if not count else canonical_decimal((squared / count).sqrt()),
        "wape": None if actual_total == 0 else canonical_decimal(absolute / actual_total),
        "bias": None if actual_total == 0 else canonical_decimal(bias / actual_total),
    }


def _operational(items: list[dict]) -> tuple[dict, dict]:
    names = {
        "stockout_cases": "stockout_quantity",
        "expired_cases": "expired_quantity",
        "interwarehouse_transfer_cases": "interwarehouse_transfer_quantity",
    }
    totals = dict.fromkeys(names, Decimal(0))
    coverage = dict.fromkeys(names, 0)
    for item in items:
        actual = item["actual"]
        if actual is None:
            continue
        for output, attribute in names.items():
            value = getattr(actual, attribute)
            if value is not None:
                totals[output] += value
                coverage[output] += 1
    return (
        {
            key: None if not coverage[key] else canonical_decimal(value)
            for key, value in totals.items()
        },
        coverage,
    )


def _case_key(value) -> tuple:
    return value.business_date.isoformat(), value.jan, value.warehouse_id


def _index_cases(items: list[dict]) -> tuple[dict, set[tuple]]:
    indexed: dict[tuple, dict] = {}
    duplicates = set()
    for item in items:
        key = _case_key(item["case"])
        if key in indexed:
            duplicates.add(key)
            indexed.pop(key, None)
        elif key not in duplicates:
            indexed[key] = item
    return indexed, duplicates


def _actual_signature(value) -> tuple | None:
    if value is None:
        return None
    return (
        value.source_version, value.source_sha256,
        value.actual_shipped_quantity, value.actual_demand_quantity,
        value.stockout_quantity, value.expired_quantity,
        value.interwarehouse_transfer_quantity,
    )


def _metric_delta(left, right):
    if left is None or right is None:
        return None
    return canonical_decimal(Decimal(left) - Decimal(right))
