"""日次buildから受入技術チェックを決定する。"""

import hashlib
from collections import Counter, defaultdict
from datetime import date, timedelta

from ..catalog.files import verify_snapshot_file
from ..daily.export import render_daily_csv
from .contracts import AcceptanceCase, AcceptanceCheck, ReportOutcome

USABLE_STATES = {"OBSERVED", "CONFIRMED_ZERO"}
HANDLED_STATES = {"OBSERVED", "CONFIRMED_ZERO", "MISSING", "PARTIAL_OR_INVALID"}


def evaluate_acceptance(case: AcceptanceCase, daily, catalog):
    definition = case.definition
    build = daily.get_job(definition["daily_build_id"])
    if build is None:
        checks = [
            _check(
                case,
                "BUILD_SUCCEEDED",
                False,
                {"status": "NOT_FOUND"},
                {"status": "SUCCEEDED"},
            )
        ]
        checks.extend(_not_evaluated(case, CHECK_IDS[1:], "日次buildが見つかりません"))
        return checks, {"limitations": _limitations(definition)}, "FAILED"
    checks = [
        _check(
            case,
            "BUILD_SUCCEEDED",
            build.status == "SUCCEEDED",
            {"status": build.status},
            {"status": "SUCCEEDED"},
        )
    ]
    if build.status != "SUCCEEDED":
        checks.extend(_not_evaluated(case, CHECK_IDS[1:], "日次buildが成功していません"))
        return checks, {"limitations": _limitations(definition)}, "FAILED"

    values = daily.list_values(build.build_id)
    expected_products = set(definition["expected_product_ids"])
    selected = build.definition["selected_series"]
    actual_products = {item["canonical_product_id"] for item in selected}
    checks.append(
        _check(
            case,
            "PRODUCT_SCOPE",
            actual_products == expected_products,
            {"product_ids": sorted(actual_products), "product_count": len(actual_products)},
            {"product_ids": sorted(expected_products), "min": 3, "max": 5},
        )
    )
    required_mode = definition["required_availability_mode"]
    actual_mode = build.definition["availability_mode"]
    checks.append(
        _check(
            case,
            "AVAILABILITY_MODE",
            actual_mode == required_mode,
            {"availability_mode": actual_mode},
            {"availability_mode": required_mode},
        )
    )
    snapshot = catalog.get_snapshot(build.snapshot_id) if build.snapshot_id else None
    linked = bool(
        snapshot
        and snapshot.manifest.get("provenance", {}).get("daily_build_id") == build.build_id
        and snapshot.manifest.get("data_sha256") == build.data_sha256
        and snapshot.manifest.get("data_uri") == build.data_uri
    )
    checks.append(
        _check(
            case,
            "SNAPSHOT_LINKED",
            linked,
            {"snapshot_id": build.snapshot_id, "linked": linked},
            {"daily_build_id": build.build_id, "linked": True},
        )
    )
    checksum_ok, checksum_detail = _verify_artifact(build, snapshot, values)
    checks.append(
        _check(
            case,
            "ARTIFACT_CHECKSUM",
            checksum_ok,
            {"sha256": build.data_sha256, "detail": checksum_detail},
            {"verified": True},
        )
    )
    series_counts, state_counts = _series_counts(values)
    expected_dates = _dates(build.definition["train_start"], build.definition["test_end"])
    expected_days = len(expected_dates)
    expected_series = {
        f"{item['canonical_product_id']}::{item['center_id']}" for item in selected
    }
    dates_by_series = defaultdict(set)
    for item in values:
        dates_by_series[item.unique_id].add(item.ds)
    calendar_ok = set(dates_by_series) == expected_series and all(
        values == expected_dates for values in dates_by_series.values()
    )
    checks.append(
        _check(
            case,
            "SERIES_CALENDAR",
            calendar_ok,
            {"days_by_series": series_counts, "row_count": len(values)},
            {"days_per_series": expected_days, "series_count": len(expected_series)},
        )
    )
    usable = _rates(values, lambda state: state in USABLE_STATES, denominator="all")
    minimum = definition["min_usable_days_per_series"]
    checks.append(
        _check(
            case,
            "USABLE_DAYS",
            set(usable) == expected_series and all(value >= minimum for value in usable.values()),
            {"usable_days_by_series": usable},
            {"minimum_per_series": minimum},
        )
    )
    missing = _rates(values, lambda state: state == "MISSING")
    checks.append(_rate_check(case, "MISSING_RATE", missing, definition["max_missing_rate"]))
    invalid = _rates(values, lambda state: state == "PARTIAL_OR_INVALID")
    checks.append(
        _rate_check(
            case, "PARTIAL_INVALID_RATE", invalid, definition["max_partial_invalid_rate"]
        )
    )
    checks.append(
        _check(
            case,
            "REAL_DATA_DECLARATION",
            definition["data_kind"] == "REAL",
            {"data_kind": definition["data_kind"]},
            {"data_kind": "REAL"},
            not_evaluated=definition["data_kind"] != "REAL",
        )
    )
    failed = any(item.status == "FAILED" for item in checks)
    outcome: ReportOutcome = (
        "FAILED" if failed else "DRY_RUN" if definition["data_kind"] == "ANONYMIZED" else "PASSED"
    )
    summary = {
        "product_count": len(actual_products),
        "series_count": len(expected_series),
        "calendar_days": expected_days,
        "row_count": len(values),
        "state_counts": dict(sorted(state_counts.items())),
        "limitations": _limitations(definition),
    }
    return checks, summary, outcome


CHECK_IDS = (
    "BUILD_SUCCEEDED",
    "PRODUCT_SCOPE",
    "AVAILABILITY_MODE",
    "SNAPSHOT_LINKED",
    "ARTIFACT_CHECKSUM",
    "SERIES_CALENDAR",
    "USABLE_DAYS",
    "MISSING_RATE",
    "PARTIAL_INVALID_RATE",
    "REAL_DATA_DECLARATION",
)


def _series_counts(values) -> tuple[dict[str, int], Counter]:
    return dict(sorted(Counter(item.unique_id for item in values).items())), Counter(
        item.state for item in values
    )


def _rates(values, predicate, denominator="handled") -> dict[str, float | int]:
    totals = defaultdict(int)
    matches = defaultdict(int)
    for item in values:
        if denominator == "all" or item.state in HANDLED_STATES:
            totals[item.unique_id] += 1
            matches[item.unique_id] += int(predicate(item.state))
    if denominator == "all":
        return dict(sorted(matches.items()))
    return {
        key: round(matches[key] / total, 12) if total else 1.0
        for key, total in sorted(totals.items())
    }


def _rate_check(case, check_id, rates, maximum):
    return _check(
        case,
        check_id,
        bool(rates) and all(value <= maximum for value in rates.values()),
        {"rate_by_series": rates},
        {"maximum_per_series": float(maximum)},
    )


def _verify_artifact(build, snapshot, values) -> tuple[bool, str]:
    if snapshot is None or not build.data_uri or not build.data_sha256:
        return False, "artifact参照がありません"
    try:
        verify_snapshot_file(build.data_uri, build.data_sha256)
    except (OSError, ValueError) as exc:
        return False, str(exc)
    ledger_sha = hashlib.sha256(render_daily_csv(values)).hexdigest()
    if ledger_sha != build.data_sha256:
        return False, "日次台帳とCSVのchecksumが一致しません"
    return True, "CSV・日次台帳・checksum一致"


def _dates(start_value: str, end_value: str) -> set[str]:
    start = date.fromisoformat(start_value)
    end = date.fromisoformat(end_value)
    return {
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    }


def _check(case, check_id, ok, actual, expected, *, not_evaluated=False):
    status = "NOT_EVALUATED" if not_evaluated else "PASSED" if ok else "FAILED"
    if status == "PASSED":
        detail = "検査済み"
    elif not_evaluated:
        detail = "匿名データのため業務受入対象外"
    else:
        detail = "条件不一致"
    return AcceptanceCheck(case.case_id, check_id, status, actual, expected, detail)


def _not_evaluated(case, check_ids, detail):
    return [
        AcceptanceCheck(case.case_id, value, "NOT_EVALUATED", {}, {}, detail)
        for value in check_ids
    ]


def _limitations(definition):
    values = ["この判定は予測精度または業務効果を保証しません"]
    if definition["data_kind"] == "ANONYMIZED":
        values.append("匿名データによる手順確認であり、実データ受入ではありません")
    if definition["required_availability_mode"] == "ASSUMED":
        values.append("当時の実到着時刻を厳密に再現していません")
    return values
