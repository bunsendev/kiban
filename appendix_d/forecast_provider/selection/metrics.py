"""日次状態から欠損と0を分離して品目統計量を算出する。"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, localcontext

from ..daily import DailyValue

USABLE_STATES = {"OBSERVED", "CONFIRMED_ZERO"}
MISSING_STATES = {"MISSING", "PARTIAL_OR_INVALID"}
HANDLED_STATES = USABLE_STATES | MISSING_STATES


@dataclass(frozen=True)
class ProductMetrics:
    canonical_product_id: str
    total_quantity: Decimal
    quantity_share: Decimal | None
    coefficient_of_variation: Decimal | None
    zero_rate: Decimal | None
    missing_rate: Decimal | None
    usable_days: int
    handled_days: int
    center_ids: tuple[str, ...]


def calculate_product_metrics(values: list[DailyValue]) -> list[ProductMetrics]:
    grouped = defaultdict(list)
    for value in values:
        grouped[value.canonical_product_id].append(value)
    raw = [_calculate(product_id, rows) for product_id, rows in sorted(grouped.items())]
    grand_total = sum((item.total_quantity for item in raw), Decimal(0))
    return [
        ProductMetrics(
            item.canonical_product_id,
            item.total_quantity,
            _ratio(item.total_quantity, grand_total) if grand_total > 0 else None,
            item.coefficient_of_variation,
            item.zero_rate,
            item.missing_rate,
            item.usable_days,
            item.handled_days,
            item.center_ids,
        )
        for item in raw
    ]


def _calculate(product_id: str, rows: list[DailyValue]) -> ProductMetrics:
    usable = [value.y for value in rows if value.state in USABLE_STATES and value.y is not None]
    handled = [value for value in rows if value.state in HANDLED_STATES]
    missing = [value for value in handled if value.state in MISSING_STATES]
    centers = sorted({value.center_id for value in handled})
    total = sum(usable, Decimal(0))
    mean = total / len(usable) if usable else None
    cv = None
    if mean is not None and mean > 0:
        with localcontext() as context:
            context.prec = 28
            variance = sum(((value - mean) ** 2 for value in usable), Decimal(0)) / len(usable)
            cv = variance.sqrt() / mean
    zeros = sum(value == 0 for value in usable)
    return ProductMetrics(
        product_id,
        total,
        None,
        cv,
        _ratio(Decimal(zeros), Decimal(len(usable))) if usable else None,
        _ratio(Decimal(len(missing)), Decimal(len(handled))) if handled else None,
        len(usable),
        len(handled),
        tuple(centers),
    )


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        return numerator / denominator
