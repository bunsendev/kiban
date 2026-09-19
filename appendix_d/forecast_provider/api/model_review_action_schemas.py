"""レビュー対応タスクAPIの入力schema。"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    action_type: Literal[
        "RETEST",
        "DATA_FIX",
        "BUSINESS_CONFIRMATION",
        "MODEL_REVIEW",
        "LIFECYCLE_TRIAL",
        "OTHER",
    ]
    title: str = Field(min_length=1, max_length=200)
    assignee: str = Field(min_length=1, max_length=200)
    due_date: date
    note: str = Field(min_length=1, max_length=1000)


class ReviewActionEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    status: Literal["OPEN", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"]
    assignee: str = Field(min_length=1, max_length=200)
    due_date: date
    note: str = Field(min_length=1, max_length=1000)
    completion_evidence: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_completion_evidence(self):
        if self.status == "COMPLETED" and not self.completion_evidence:
            raise ValueError("完了時はcompletion_evidenceが必要です")
        if self.status != "COMPLETED" and self.completion_evidence is not None:
            raise ValueError("completion_evidenceは完了時だけ記録できます")
        return self
