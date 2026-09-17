"""Provider Workerの稼働heartbeat契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class WorkerState(StrEnum):
    IDLE = "IDLE"
    WORKING = "WORKING"


@dataclass(frozen=True)
class WorkerHeartbeat:
    worker_id: str
    instance_id: str
    provider_id: str
    state: WorkerState
    current_run_id: str | None
    started_at: datetime
    heartbeat_at: datetime


class StaleWorkerHeartbeat(RuntimeError):
    """同じworker IDで置き換えられた旧processからのheartbeat。"""


class WorkerStatusStore(Protocol):
    def register(
        self,
        worker_id: str,
        instance_id: str,
        provider_id: str,
        *,
        now: datetime | None = None,
    ) -> WorkerHeartbeat: ...

    def heartbeat(
        self,
        worker_id: str,
        instance_id: str,
        state: WorkerState,
        current_run_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> WorkerHeartbeat: ...

    def list_workers(self) -> list[WorkerHeartbeat]: ...
