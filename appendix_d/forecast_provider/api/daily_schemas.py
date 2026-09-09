"""予定完全性・日次build APIの入出力schema。"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlannedFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logical_path: str = Field(min_length=1)
    center_id: str = Field(min_length=1)
    file_type: str = Field(min_length=1)
    target_start: date
    target_end: date
    absence_means_zero: bool


class FileScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule_version: str = Field(min_length=1)
    valid_from: date
    valid_to: date
    files: list[PlannedFileInput] = Field(min_length=1)


class ClosedDayCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    center_id: str = Field(min_length=1)
    closed_date: date
    closure_version: str = Field(min_length=1)
    available_at: datetime
    approved_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class SelectedSeriesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_product_id: str = Field(min_length=1)
    center_id: str = Field(min_length=1)


class DailyBuildCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule_id: str = Field(min_length=1)
    normalization_ids: list[str] = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    period_version: str = Field(min_length=1)
    closure_version: str | None = None
    as_of: datetime
    selection_version: str = Field(min_length=1)
    selected_series: list[SelectedSeriesInput] = Field(min_length=1)
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    origin_interval_days: int = Field(ge=1)
    max_horizon: int = Field(ge=1, le=400)
    primary_horizon_max: int = Field(ge=1, le=400)
    report_horizons: list[int] = Field(min_length=1)
    availability_mode: Literal["ASSUMED", "OBSERVED"]
