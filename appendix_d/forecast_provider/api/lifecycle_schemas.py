"""Model lifecycle APIの入力schema。"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LifecyclePlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_version: str = Field(min_length=1)
    adoption_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    schedule_day: int = Field(default=1, ge=1, le=28)
    schedule_time: str = Field(default="02:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="Asia/Tokyo", min_length=1)
    trial_start_date: date
    metric: Literal["wape_pct"] = "wape_pct"
    minimum_improvement_pct: float = Field(default=0, ge=0, le=100)
    maximum_failure_rate: float = Field(default=0, ge=0, le=1)
    created_by: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1)


class CycleComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenger_run_id: str = Field(min_length=1)
    comparison_id: str = Field(min_length=1)


class CycleFail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failure_code: str = Field(min_length=1, max_length=120)


class PromoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    approved_by: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1)


class RollbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_run_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    approved_by: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1)


class TrialForecastCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1)
    origin_date: date
    recorded_by: str | None = Field(default=None, min_length=1)


class TrialAssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    period_start: date
    period_end: date
    comparison_id: str = Field(min_length=1)
    decision: Literal["CONTINUE", "COMPLETE", "ROLLBACK"]
    assessed_by: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1)

