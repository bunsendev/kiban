"""固定学習と月次拡大学習で共有する学習スケジュール。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Literal

from .contracts import ForecastDataset
from .errors import ContractViolationError

TrainingPolicy = Literal["FIXED", "MONTHLY_EXPANDING"]
SUPPORTED_TRAINING_POLICIES = frozenset({"FIXED", "MONTHLY_EXPANDING"})


def normalize_training_policy(value: object) -> TrainingPolicy:
    if value not in SUPPORTED_TRAINING_POLICIES:
        raise ContractViolationError("training_policyが不正です")
    return value  # type: ignore[return-value]


def training_cutoff(
    dataset: ForecastDataset, origin: date, policy: TrainingPolicy | str
) -> date:
    """originへ適用する学習締切を決める。月の最初の予定originだけ再学習する。"""
    normalized = normalize_training_policy(policy)
    origins = dataset.origin_dates()
    if origin not in origins:
        raise ContractViolationError("予定外originの学習締切は計算できません")
    if normalized == "FIXED":
        return dataset.train_end
    month = (origin.year, origin.month)
    return next(value for value in origins if (value.year, value.month) == month)


def training_cutoffs(
    dataset: ForecastDataset, policy: TrainingPolicy | str
) -> tuple[date, ...]:
    """実験で予定される実際の学習締切を返す。年12回という固定値を持たない。"""
    normalized = normalize_training_policy(policy)
    if normalized == "FIXED":
        return (dataset.train_end,)
    result: list[date] = []
    seen: set[tuple[int, int]] = set()
    for origin in dataset.origin_dates():
        key = (origin.year, origin.month)
        if key not in seen:
            result.append(origin)
            seen.add(key)
    return tuple(result)


def training_dataset(dataset: ForecastDataset, cutoff: date) -> ForecastDataset:
    """元の開始日を保ち、指定締切まで拡大した学習用datasetを作る。"""
    if cutoff < dataset.train_end or cutoff >= dataset.test_end:
        raise ContractViolationError("学習締切が実験期間外です")
    return replace(dataset, train_end=cutoff, test_start=cutoff + timedelta(days=1))


def calendar_month(origin: date) -> tuple[date, date]:
    """originを含む月の半開区間を返す。artifactの月内再利用に用いる。"""
    start = origin.replace(day=1)
    after = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, after
