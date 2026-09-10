"""受入APIの入出力schema。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AcceptanceCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acceptance_version: str = Field(min_length=1)
    daily_build_id: str = Field(min_length=1)
    data_kind: Literal["REAL", "ANONYMIZED"]
    expected_product_ids: list[str] = Field(min_length=3, max_length=5)
    required_availability_mode: Literal["ASSUMED", "OBSERVED"]
    min_usable_days_per_series: int = Field(ge=1)
    max_missing_rate: float = Field(ge=0, le=1)
    max_partial_invalid_rate: float = Field(ge=0, le=1)
    requested_by: str | None = Field(default=None, min_length=1)
    purpose: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_products(self):
        if len(set(self.expected_product_ids)) != len(self.expected_product_ids):
            raise ValueError("expected_product_idsは重複できません")
        return self


class AcceptanceDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_version: str = Field(min_length=1)
    decision: Literal["APPROVED", "REJECTED"]
    decided_by: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1)
