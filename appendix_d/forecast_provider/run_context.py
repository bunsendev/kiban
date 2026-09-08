"""実行情報と情報利用締切。Provider固有処理・runnerへ依存しない。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from numbers import Integral
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

import pandas as pd

from .errors import ContractViolationError

if TYPE_CHECKING:
    from .contracts import ContextRef, ModelRef
    from .failures import FailureSink

AvailabilityMode = Literal["ASSUMED", "OBSERVED"]
JST = ZoneInfo("Asia/Tokyo")


def validate_cutoff(cutoff_at: datetime) -> None:
    if (
        not isinstance(cutoff_at, datetime)
        or pd.isna(cutoff_at)
        or cutoff_at.tzinfo is None
        or cutoff_at.utcoffset() is None
    ):
        raise ValueError("cutoff_atはtimezone付き・非欠損datetimeで指定します")


def cutoff_for_origin(origin_date: date) -> datetime:
    if not isinstance(origin_date, date) or isinstance(origin_date, datetime):
        raise ValueError("origin_dateは時刻を含まないdateで指定します")
    return datetime.combine(origin_date + timedelta(days=1), time.min, JST)


@dataclass(frozen=True)
class RunContext:
    """deadlineは実行期限、cutoff_atは利用可能な情報の締切。"""

    run_id: str
    experiment_id: str
    seed: int
    deadline: datetime
    input_dir: Path
    output_dir: Path
    resource_profile: str
    logger: logging.Logger
    availability_mode: AvailabilityMode = field(kw_only=True)
    cutoff_at: datetime = field(kw_only=True)
    origin_date: date | None = field(default=None, kw_only=True)
    failure_sink: FailureSink | None = field(default=None, kw_only=True, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.availability_mode not in ("ASSUMED", "OBSERVED"):
            raise ValueError("availability_modeはASSUMED/OBSERVEDで指定します")
        validate_cutoff(self.cutoff_at)
        if isinstance(self.seed, bool) or not isinstance(self.seed, Integral):
            raise ValueError("seedはbool以外の整数で指定します")
        object.__setattr__(self, "seed", int(self.seed))
        if self.origin_date is not None:
            cutoff_for_origin(self.origin_date)

    def for_origin(self, origin_date: date) -> RunContext:
        """共有情報を維持し、fitにはTRAIN_END、予測には対象originを指定する。"""
        return replace(self, origin_date=origin_date, cutoff_at=cutoff_for_origin(origin_date))

    def validate_for_origin(self, origin_date: date, availability_mode: str) -> None:
        if self.availability_mode != availability_mode:
            raise ContractViolationError("RunContextと学習条件のavailability_mode不一致")
        if self.origin_date != origin_date:
            raise ContractViolationError("RunContext.origin_date不一致")
        if self.cutoff_at != cutoff_for_origin(origin_date):
            raise ContractViolationError("RunContext.cutoff_atは起点翌日00:00 JSTです")


def validate_context_ref(model: ModelRef, ref: ContextRef, context: RunContext) -> None:
    """Provider直接呼出し・runner両方の境界で参照の取り違えを防ぐ。"""
    context.validate_for_origin(ref.origin_date, model.availability_mode)
    if ref.model_id != model.model_id:
        raise ContractViolationError("ContextRef.model_id不一致")
    if ref.cutoff_at != context.cutoff_at:
        raise ContractViolationError("ContextRef.cutoff_at不一致")
    if ref.history_end > ref.origin_date:
        raise ContractViolationError("ContextRef.history_endがorigin_dateを超えています")
