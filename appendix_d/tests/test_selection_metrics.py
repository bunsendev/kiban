"""欠損を0へ変換しない重要品目統計量。"""

from decimal import Decimal

from forecast_provider.daily import DailyValue
from forecast_provider.selection.classification import build_candidates
from forecast_provider.selection.metrics import calculate_product_metrics


def value(product, day, state, quantity, center="C1"):
    return DailyValue(
        "daily-1",
        product,
        center,
        f"2026-01-0{day}",
        f"{product}::{center}",
        quantity,
        quantity,
        state,
        "2026-01-10T00:00:00+00:00",
    )


def test_cv_and_zero_rate_use_only_observed_and_confirmed_zero():
    rows = [
        value("P1", 1, "OBSERVED", Decimal(10)),
        value("P1", 2, "MISSING", None),
        value("P1", 3, "CONFIRMED_ZERO", Decimal(0)),
        value("P1", 4, "CLOSED", None),
        value("P1", 5, "NOT_HANDLED", None),
    ]
    result = calculate_product_metrics(rows)[0]
    assert result.total_quantity == 10
    assert result.usable_days == 2
    assert result.handled_days == 3
    assert result.coefficient_of_variation == 1
    assert result.zero_rate == Decimal("0.5")
    assert result.missing_rate == Decimal(1) / Decimal(3)


def test_quantity_share_uses_all_products_in_same_job():
    rows = [
        value("P1", 1, "OBSERVED", Decimal(30)),
        value("P2", 1, "OBSERVED", Decimal(10)),
    ]
    by_product = {
        item.canonical_product_id: item for item in calculate_product_metrics(rows)
    }
    assert by_product["P1"].quantity_share == Decimal("0.75")
    assert by_product["P2"].quantity_share == Decimal("0.25")


def test_all_zero_job_has_no_quantity_share_or_cv():
    result = calculate_product_metrics(
        [value("P1", 1, "CONFIRMED_ZERO", Decimal(0))]
    )[0]
    assert result.quantity_share is None
    assert result.coefficient_of_variation is None
    assert result.zero_rate == 1


def test_classification_and_eligibility_are_explicit():
    metrics = calculate_product_metrics(
        [
            value("P1", 1, "OBSERVED", Decimal(10)),
            value("P1", 2, "MISSING", None),
            value("P2", 1, "CONFIRMED_ZERO", Decimal(0)),
        ]
    )
    candidates = build_candidates(
        "job-1",
        metrics,
        {"P1"},
        {"P2"},
        Decimal("0.4"),
        Decimal("1"),
        Decimal("0.5"),
    )
    by_product = {item.canonical_product_id: item for item in candidates}
    assert {"STABLE", "JAN_CHANGED"}.issubset(by_product["P1"].tags)
    assert {"INTERMITTENT", "BUSINESS_DESIGNATED"}.issubset(by_product["P2"].tags)
    assert by_product["P1"].eligible is False
    assert by_product["P1"].ineligibility_reason
