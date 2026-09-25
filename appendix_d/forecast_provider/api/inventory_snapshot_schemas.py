"""Phase 3S-4 inventory APIの境界schema。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InventorySnapshotJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_reference: str = Field(min_length=1, max_length=1_024)
    source_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    mapping_version: str = Field(min_length=1, max_length=100)
    known_at: datetime

    @field_validator("known_at")
    @classmethod
    def aware_known_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("known_atはtimezone付き日時です")
        return value


class InventorySnapshotDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["APPROVED", "REJECTED"]
    expected_revision: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def rejected_reason(self):
        if self.decision == "REJECTED" and not (self.reason or "").strip():
            raise ValueError("REJECTEDにはreasonが必要です")
        return self
