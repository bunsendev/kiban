"""起点境界で再開できる小さなWorker。"""

from __future__ import annotations

import queue
import threading
import time
import uuid

from ..errors import ProviderError
from .contracts import OriginExecutor, OriginOutput, RunStatus, RunStore


def resume_run(
    store: RunStore,
    run_id: str,
    condition_fingerprint: str,
    execute: OriginExecutor,
    *,
    worker_id: str | None = None,
    lease_seconds: int = 60,
    origin_timeout_seconds: float = 600,
    max_origins: int | None = None,
) -> RunStatus:
    """未完了起点だけを実行する。成功済み起点はstoreがclaimしない。"""
    if store.cancellation_requested(run_id):
        return store.finish_run(run_id)
    store.start_or_resume(run_id, condition_fingerprint)
    worker_id = worker_id or str(uuid.uuid4())
    completed = 0
    while not store.cancellation_requested(run_id):
        if max_origins is not None and completed >= max_origins:
            break
        store.reclaim_expired(run_id)
        lease = store.claim_next_origin(run_id, worker_id, lease_seconds)
        if lease is None:
            break
        try:
            output = _bounded_execute(store, execute, lease, origin_timeout_seconds, lease_seconds)
        except ProviderError as exc:
            store.fail_origin(lease, type(exc).__name__, retryable=exc.retryable)
        except Exception as exc:
            store.fail_origin(lease, type(exc).__name__, retryable=False)
        else:
            store.complete_origin(lease, output)
        completed += 1
    return store.finish_run(run_id)


def _bounded_execute(
    store: RunStore,
    execute: OriginExecutor,
    lease,
    timeout_seconds: float,
    lease_seconds: int,
) -> OriginOutput:
    """daemon threadで待機時間を制限する。遅延結果はstoreへ渡さない。"""
    if timeout_seconds <= 0:
        raise ValueError("origin_timeout_secondsは正数です")
    result: queue.Queue = queue.Queue(maxsize=1)

    def invoke() -> None:
        try:
            result.put((True, execute(lease)))
        except BaseException as exc:
            result.put((False, exc))

    threading.Thread(target=invoke, daemon=True).start()
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            from ..errors import TimeoutProviderError

            raise TimeoutProviderError("起点の実行時間上限を超えました")
        try:
            ok, value = result.get(timeout=min(remaining, lease_seconds / 3))
            break
        except queue.Empty:
            lease = store.heartbeat(lease, lease_seconds)
    if ok:
        return value
    raise value
