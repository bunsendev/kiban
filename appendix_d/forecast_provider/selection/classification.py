"""候補の分類、適格性、決定的な順位を組み立てる。"""

from decimal import Decimal

from .contracts import SelectionCandidate
from .metrics import ProductMetrics


def build_candidates(
    candidate_job_id: str,
    metrics: list[ProductMetrics],
    jan_changed_ids: set[str],
    business_product_ids: set[str],
    max_missing_rate: Decimal,
    stable_cv_max: Decimal,
    intermittent_zero_rate_min: Decimal,
) -> list[SelectionCandidate]:
    candidates = [
        _build(
            candidate_job_id,
            item,
            item.canonical_product_id in jan_changed_ids,
            item.canonical_product_id in business_product_ids,
            max_missing_rate,
            stable_cv_max,
            intermittent_zero_rate_min,
        )
        for item in metrics
    ]
    candidates.sort(
        key=lambda item: (
            not item.business_designated,
            -item.total_quantity,
            item.missing_rate if item.missing_rate is not None else Decimal("Infinity"),
            item.canonical_product_id,
        )
    )
    return [
        SelectionCandidate(**{**item.__dict__, "rank": rank})
        for rank, item in enumerate(candidates, 1)
    ]


def _build(
    job_id: str,
    item: ProductMetrics,
    jan_changed: bool,
    business_designated: bool,
    max_missing_rate: Decimal,
    stable_cv_max: Decimal,
    intermittent_zero_rate_min: Decimal,
) -> SelectionCandidate:
    tags = []
    if item.coefficient_of_variation is not None and item.coefficient_of_variation <= stable_cv_max:
        tags.append("STABLE")
    if item.zero_rate is not None and item.zero_rate >= intermittent_zero_rate_min:
        tags.append("INTERMITTENT")
    if jan_changed:
        tags.append("JAN_CHANGED")
    if business_designated:
        tags.append("BUSINESS_DESIGNATED")
    reason = None
    if item.handled_days == 0:
        reason = "取扱対象日がありません"
    elif item.usable_days == 0:
        reason = "利用可能な実績がありません"
    elif item.missing_rate is None or item.missing_rate > max_missing_rate:
        reason = "欠損率が上限を超えています"
    return SelectionCandidate(
        job_id,
        item.canonical_product_id,
        0,
        item.total_quantity,
        item.quantity_share,
        item.coefficient_of_variation,
        item.zero_rate,
        item.missing_rate,
        item.usable_days,
        item.handled_days,
        jan_changed,
        business_designated,
        item.center_ids,
        tuple(tags),
        reason is None,
        reason,
    )
