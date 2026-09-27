"""倉庫の賞味期限bucketを日付順に消化する純粋なShadow計算。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from ..inventory_foundation.domain import canonical_datetime, canonical_decimal
from ..warehouse_projection.domain import WarehouseProjection


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ExpiryPolicy:
    policy_version: str
    minimum_remaining_days: int
    attention_days: int
    confirmed_by: str
    reason: str
    confirmed_at: datetime


def build_expiry_policy(
    *, minimum_remaining_days: int, attention_days: int,
    confirmed_by: str, reason: str, confirmed_at: datetime,
) -> ExpiryPolicy:
    """期限日を含め何日前まで提供可能かを明示的な業務条件として固定する。"""

    if isinstance(minimum_remaining_days, bool) or not isinstance(minimum_remaining_days, int):
        raise ValueError("minimum_remaining_daysは整数です")
    if isinstance(attention_days, bool) or not isinstance(attention_days, int):
        raise ValueError("attention_daysは整数です")
    if minimum_remaining_days < 0 or attention_days < 0:
        raise ValueError("policyの日数は0以上です")
    if not confirmed_by.strip() or not reason.strip():
        raise ValueError("policyの確認者と理由は必須です")
    timestamp = canonical_datetime(confirmed_at, "confirmed_at")
    payload = {
        "format_version": "expiry-policy-v1",
        "minimum_remaining_days": minimum_remaining_days,
        "attention_days": attention_days,
        "confirmed_by": confirmed_by.strip(),
        "reason": reason.strip(),
        "confirmed_at": timestamp,
    }
    return ExpiryPolicy(
        f"expiry-policy-{_digest(payload)}", minimum_remaining_days, attention_days,
        confirmed_by.strip(), reason.strip(), confirmed_at.astimezone(UTC),
    )


@dataclass(frozen=True)
class ExpiryBucketResult:
    expiry_date: date
    last_usable_date: date
    opening_cases: Decimal
    consumed_cases: Decimal
    unconsumed_by_cutoff_cases: Decimal
    remaining_after_horizon_cases: Decimal


@dataclass(frozen=True)
class ExpiryDay:
    business_date: date
    forecast_demand_cases: Decimal
    consumed_cases: Decimal
    unmet_cases: Decimal
    unconsumed_by_cutoff_cases: Decimal
    ending_usable_cases: Decimal
    attention_cases: Decimal


@dataclass(frozen=True)
class ExpirySimulation:
    simulation_id: str
    content_sha256: str
    projection_id: str
    policy_version: str
    jan: str
    warehouse_id: str
    opening_cases: Decimal
    consumed_cases: Decimal
    unconsumed_by_cutoff_cases: Decimal
    remaining_after_horizon_cases: Decimal
    unmet_demand_cases: Decimal
    buckets: tuple[ExpiryBucketResult, ...]
    days: tuple[ExpiryDay, ...]


def simulate_expiry(
    projection: WarehouseProjection,
    buckets: tuple[tuple[date, Decimal | int | str], ...],
    policy: ExpiryPolicy,
) -> ExpirySimulation:
    """各日、利用期限の早いbucketから需要を引き、未消化分を期限日に計上。"""

    if not buckets:
        raise ValueError("賞味期限bucketがありません")
    if policy.confirmed_at > projection.calculation_at:
        raise ValueError("policyは計算時点に未確定です")
    first_day = projection.days[0].business_date
    snapshot_day = projection.forecast_origin_date
    if first_day != snapshot_day + timedelta(days=1):
        raise ValueError("projection起点と翌日の関係が不正です")
    grouped: dict[date, Decimal] = {}
    for expiry_date, raw_quantity in buckets:
        if isinstance(expiry_date, datetime) or not isinstance(expiry_date, date):
            raise ValueError("賞味期限不明・不正bucketは計算できません")
        if expiry_date < snapshot_day:
            raise ValueError("snapshot時点で期限切れのbucketです")
        quantity = Decimal(canonical_decimal(raw_quantity))
        if quantity < 0:
            raise ValueError("bucket数量は0以上です")
        grouped[expiry_date] = grouped.get(expiry_date, Decimal("0")) + quantity
    opening = sum(grouped.values(), Decimal("0"))
    if opening != projection.starting_inventory_cases:
        raise ValueError("bucket数量とProjection開始在庫が一致しません")
    expiries = sorted(grouped)
    remaining = dict(grouped)
    consumed = {expiry: Decimal("0") for expiry in expiries}
    lost = {expiry: Decimal("0") for expiry in expiries}
    cutoff = {
        expiry: expiry - timedelta(days=policy.minimum_remaining_days)
        for expiry in expiries
    }
    days = []
    for point in projection.days:
        day = point.business_date
        day_lost = Decimal("0")
        # 既に利用期限を過ぎたbucketは、当日の需要へ充当しない。
        for expiry in expiries:
            if cutoff[expiry] < day and remaining[expiry]:
                day_lost += remaining[expiry]
                lost[expiry] += remaining[expiry]
                remaining[expiry] = Decimal("0")
        demand_left = point.forecast_demand_cases
        day_consumed = Decimal("0")
        for expiry in expiries:
            if demand_left == 0:
                break
            available = remaining[expiry]
            taken = min(available, demand_left)
            consumed[expiry] += taken
            remaining[expiry] -= taken
            demand_left -= taken
            day_consumed += taken
        # 期限当日の需要を処理した後の未消化量を見込み損失とする。
        for expiry in expiries:
            if cutoff[expiry] == day and remaining[expiry]:
                day_lost += remaining[expiry]
                lost[expiry] += remaining[expiry]
                remaining[expiry] = Decimal("0")
        attention_until = day + timedelta(days=policy.attention_days)
        days.append(ExpiryDay(
            day, point.forecast_demand_cases, day_consumed, demand_left, day_lost,
            sum(remaining.values(), Decimal("0")),
            sum((remaining[expiry] for expiry in expiries
                 if day < cutoff[expiry] <= attention_until), Decimal("0")),
        ))
    results = tuple(
        ExpiryBucketResult(expiry, cutoff[expiry], grouped[expiry], consumed[expiry],
                           lost[expiry], remaining[expiry])
        for expiry in expiries
    )
    total_consumed = sum(consumed.values(), Decimal("0"))
    total_lost = sum(lost.values(), Decimal("0"))
    total_remaining = sum(remaining.values(), Decimal("0"))
    assert opening == total_consumed + total_lost + total_remaining
    payload = {
        "format_version": "expiry-simulation-v1",
        "projection_id": projection.projection_id,
        "policy_version": policy.policy_version,
        "buckets": [(item.expiry_date.isoformat(), canonical_decimal(item.opening_cases))
                    for item in results],
    }
    digest = _digest(payload)
    return ExpirySimulation(
        f"expiry-simulation-{digest}", digest, projection.projection_id,
        policy.policy_version, projection.jan, projection.warehouse_id, opening,
        total_consumed, total_lost, total_remaining,
        sum((point.unmet_cases for point in days), Decimal("0")), results, tuple(days),
    )
