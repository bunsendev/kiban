from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OperationEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    flow_session_id: UUID
    screen: Literal["easy"]
    event_name: Literal[
        "CONNECTED",
        "SOURCE_MODE_CHANGED",
        "SOURCE_SELECTED",
        "SOURCE_CLEARED",
        "ANALYSIS_REQUESTED",
        "ANALYSIS_ACCEPTED",
        "ANALYSIS_FAILED",
        "STEP_VIEWED",
        "STEP_COMPLETED",
    ]
    step: int = Field(ge=1, le=4)
    sequence: int = Field(ge=1, le=10_000)
    outcome: Literal["INFO", "SUCCESS", "FAILURE", "CANCELLED"]
    elapsed_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    metadata: dict[str, str | int | bool | None] = Field(default_factory=dict)
    occurred_at: datetime
