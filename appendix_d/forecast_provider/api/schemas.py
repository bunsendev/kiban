"""HTTP入出力schema。DB型やFastAPI routeから分離する。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..run_context import cutoff_for_origin


class OriginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin_date: date
    cutoff_at: datetime

    @model_validator(mode="after")
    def validate_cutoff(self):
        if self.cutoff_at.tzinfo is None or self.cutoff_at.utcoffset() is None:
            raise ValueError("cutoff_atはtimezone付きです")
        if self.cutoff_at != cutoff_for_origin(self.origin_date):
            raise ValueError("cutoff_atはorigin翌日00:00 JSTです")
        return self


class ExpectationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unique_id: str = Field(min_length=1)
    origin_date: date
    target_date: date
    horizon: int = Field(ge=1, le=400)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.target_date <= self.origin_date:
            raise ValueError("target_dateはorigin_dateより後です")
        if self.horizon != (self.target_date - self.origin_date).days:
            raise ValueError("horizonはtarget_date-origin_dateです")
        return self


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: str = Field(min_length=1)
    condition_fingerprint: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    seed: int
    origins: tuple[OriginInput, ...] = Field(min_length=1)
    expectations: tuple[ExpectationInput, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_plan(self):
        origins = [item.origin_date for item in self.origins]
        if len(origins) != len(set(origins)):
            raise ValueError("origin_dateに重複があります")
        origin_set = set(origins)
        if any(item.origin_date not in origin_set for item in self.expectations):
            raise ValueError("expectationのoriginが未定義です")
        keys = [(x.unique_id, x.origin_date, x.target_date) for x in self.expectations]
        if len(keys) != len(set(keys)):
            raise ValueError("expectationに重複があります")
        return self


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition_fingerprint: str = Field(min_length=1)


class RunCreated(BaseModel):
    run_id: str
    status: str


class RunStatusOutput(BaseModel):
    run_id: str
    experiment_id: str
    status: str
    cancellation_requested: bool
    origin_counts: dict[str, int]
    failure_count: int
