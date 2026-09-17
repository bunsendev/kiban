"""Provider metadata、run queue、heartbeatを結合する参照サービス。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..registry import registry
from .contracts import WorkerState, WorkerStatusStore


class WorkerStatusService:
    def __init__(
        self, runs, workers: WorkerStatusStore | None, *, stale_seconds: float = 45
    ) -> None:
        if stale_seconds <= 0:
            raise ValueError("stale_secondsは正数です")
        self.runs = runs
        self.workers = workers
        self.stale_after = timedelta(seconds=stale_seconds)

    def list_status(self, *, now: datetime | None = None) -> list[dict]:
        current = _utc(now)
        metadata = {item.provider_id: item for item in registry.list_metadata()}
        queue = self.runs.count_active_runs_by_provider()
        records = [] if self.workers is None else self.workers.list_workers()
        provider_ids = sorted(set(metadata) | set(queue) | {item.provider_id for item in records})
        result = []
        for provider_id in provider_ids:
            provider_workers = [item for item in records if item.provider_id == provider_id]
            worker_values = [self._worker_value(item, current) for item in provider_workers]
            online = [item for item in worker_values if item["liveness"] == "ONLINE"]
            if any(item["state"] == WorkerState.WORKING.value for item in online):
                status = "WORKING"
            elif online:
                status = "ONLINE"
            elif worker_values:
                status = "STALE"
            else:
                status = "NOT_STARTED"
            counts = queue.get(provider_id, {})
            provider = metadata.get(provider_id)
            result.append(
                {
                    "provider_id": provider_id,
                    "display_name": provider.display_name if provider else provider_id,
                    "status": status,
                    "queued_runs": counts.get("QUEUED", 0),
                    "running_runs": counts.get("RUNNING", 0),
                    "last_heartbeat": max(
                        (item.heartbeat_at for item in provider_workers), default=None
                    ),
                    "workers": worker_values,
                }
            )
        return result

    def _worker_value(self, value, now: datetime) -> dict:
        liveness = "ONLINE" if now - value.heartbeat_at <= self.stale_after else "STALE"
        return {
            "worker_id": value.worker_id,
            "state": value.state.value,
            "current_run_id": value.current_run_id,
            "started_at": value.started_at,
            "heartbeat_at": value.heartbeat_at,
            "liveness": liveness,
        }


def _utc(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("参照時刻はtimezone付きです")
    return result.astimezone(UTC)
