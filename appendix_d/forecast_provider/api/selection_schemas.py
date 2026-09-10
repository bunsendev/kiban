"""重要品目候補・確定選定版APIの入力schema。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CandidateJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_version: str = Field(min_length=1)
    daily_build_id: str = Field(min_length=1)
    business_product_ids: list[str] = Field(default_factory=list)
    max_missing_rate: float = Field(ge=0, le=1)
    stable_cv_max: float = Field(ge=0)
    intermittent_zero_rate_min: float = Field(ge=0, le=1)
    requested_by: str = Field(min_length=1)
    purpose: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_products(self):
        if len(set(self.business_product_ids)) != len(self.business_product_ids):
            raise ValueError("business_product_idsは重複できません")
        return self


class SelectionItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_product_id: str = Field(min_length=1)
    center_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_centers(self):
        if len(set(self.center_ids)) != len(self.center_ids):
            raise ValueError("center_idsは重複できません")
        return self


class SelectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection_version: str = Field(min_length=1)
    candidate_job_id: str = Field(min_length=1)
    scope: Literal["INITIAL", "FULL"]
    items: list[SelectionItemCreate]
    selected_by: str = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_items(self):
        product_ids = [item.canonical_product_id for item in self.items]
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("選定品目は重複できません")
        return self
