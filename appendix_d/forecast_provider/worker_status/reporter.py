"""Worker processからheartbeatを更新する小さな状態管理。"""

from __future__ import annotations

import uuid

from .contracts import WorkerState, WorkerStatusStore


class WorkerStatusReporter:
    def __init__(self, store: WorkerStatusStore, worker_id: str, provider_id: str) -> None:
        self.store = store
        self.worker_id = worker_id
        self.provider_id = provider_id
        self.instance_id = str(uuid.uuid4())
        self.state = WorkerState.IDLE
        self.current_run_id: str | None = None

    def start(self) -> None:
        self.store.register(self.worker_id, self.instance_id, self.provider_id)

    def working(self, run_id: str) -> None:
        self.state = WorkerState.WORKING
        self.current_run_id = run_id
        self.pulse()

    def idle(self) -> None:
        self.state = WorkerState.IDLE
        self.current_run_id = None
        self.pulse()

    def pulse(self) -> None:
        self.store.heartbeat(
            self.worker_id,
            self.instance_id,
            self.state,
            self.current_run_id,
        )
