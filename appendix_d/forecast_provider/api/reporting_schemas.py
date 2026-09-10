"""比較CSVと採用判断のHTTP入力。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReportExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    export_version: str = Field(min_length=1)
    baseline_run_id: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)


class AdoptionTargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection_version: str = Field(min_length=1)
    canonical_product_ids: list[str] = Field(min_length=1)
    center_ids: list[str] = Field(min_length=1)
    trial_period_days: int = Field(ge=30, le=366)


class AdoptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adoption_version: str = Field(min_length=1)
    comparison_id: str = Field(min_length=1)
    acceptance_case_id: str | None = None
    decision: Literal["ADOPTED", "REJECTED"]
    selected_run_id: str | None = None
    fallback_run_id: str | None = None
    target: AdoptionTargetInput
    decided_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_decision_references(self):
        references = (self.acceptance_case_id, self.selected_run_id, self.fallback_run_id)
        if self.decision == "ADOPTED" and any(value is None for value in references):
            raise ValueError("ADOPTEDには受入case、採用run、fallback runが必要です")
        if self.decision == "REJECTED" and any(value is not None for value in references):
            raise ValueError("REJECTEDでは受入case・runを指定しません")
        return self
