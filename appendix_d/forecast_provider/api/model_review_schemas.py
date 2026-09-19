"""モデル精度変化レビューAPIの入力schema。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelDriftReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comparison_profile_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_version: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    conclusion: Literal[
        "INVESTIGATING",
        "DATA_ISSUE",
        "BUSINESS_EVENT",
        "MODEL_ISSUE",
        "NO_ACTION",
    ]
    reason: str = Field(min_length=1, max_length=1000)
    action: str = Field(min_length=1, max_length=1000)
