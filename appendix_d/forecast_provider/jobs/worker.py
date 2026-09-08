"""起点境界で再開できる小さなWorker。"""

from __future__ import annotations

from ..errors import ProviderError
from .contracts import OriginExecutor, RunStatus, RunStore


def resume_run(
    store: RunStore,
    run_id: str,
    condition_fingerprint: str,
    execute: OriginExecutor,
) -> RunStatus:
    """未完了起点だけを実行する。成功済み起点はstoreがclaimしない。"""
    store.start_or_resume(run_id, condition_fingerprint)
    while not store.cancellation_requested(run_id):
        lease = store.claim_next_origin(run_id)
        if lease is None:
            break
        try:
            output = execute(lease)
        except ProviderError as exc:
            store.fail_origin(lease, type(exc).__name__, retryable=exc.retryable)
        except Exception as exc:
            store.fail_origin(lease, type(exc).__name__, retryable=False)
        else:
            store.complete_origin(lease, output)
    return store.finish_run(run_id)
