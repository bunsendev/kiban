"""現場担当者の選択式フィードバック。原値と自由記述を受け取らない。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from .improvement_events import ImprovementEventLedger

Step = Literal["UPLOAD", "CHECK", "RESULT", "FINISH"]
Issue = Literal["UNCLEAR", "BLOCKED", "NOT_UPDATED", "WRONG_RESULT", "OTHER"]
Action = Literal["REFRESH", "SCAN_REQUESTED", "DETAIL_OPENED", "FINISH_REQUESTED"]


class OperatorFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: Step
    issue: Issue


class OperatorAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action


def record_feedback(ledger: ImprovementEventLedger, value: OperatorFeedback) -> None:
    ledger.append(
        "OPERATOR_FEEDBACK", outcome="REVIEW",
        business_date=datetime.now(ZoneInfo("Asia/Tokyo")).date(),
        error_code=f"OPERATOR_{value.step}_{value.issue}",
    )


def record_action(ledger: ImprovementEventLedger, value: OperatorAction) -> None:
    ledger.append(
        "OPERATOR_ACTION", outcome="OK",
        business_date=datetime.now(ZoneInfo("Asia/Tokyo")).date(),
        error_code=f"ACTION_{value.action}",
    )
