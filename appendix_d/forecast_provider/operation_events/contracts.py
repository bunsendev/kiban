from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class OperationEvent:
    event_id: str
    flow_session_id: str
    subject: str
    screen: str
    event_name: str
    step: int
    sequence: int
    outcome: str
    elapsed_ms: int | None
    metadata: dict[str, str | int | bool | None]
    occurred_at: datetime
    received_at: datetime
