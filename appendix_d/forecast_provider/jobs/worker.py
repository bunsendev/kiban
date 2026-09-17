"""起点境界で再開できる小さなWorker。"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Callable
from decimal import Decimal

from ..errors import ProviderError
from ..resource_cost.contracts import ResourceCostStore, ResourceMetric, ResourceUsage
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
    resource_cost: ResourceCostStore | None = None,
    heartbeat: Callable[[], None] | None = None,
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
        if heartbeat is not None:
            heartbeat()
        try:
            output = _measured_execute(
                store,
                execute,
                lease,
                origin_timeout_seconds,
                lease_seconds,
                resource_cost,
                heartbeat,
            )
        except ProviderError as exc:
            store.fail_origin(lease, type(exc).__name__, retryable=exc.retryable)
        except Exception as exc:
            store.fail_origin(lease, type(exc).__name__, retryable=False)
        else:
            store.complete_origin(lease, output)
        completed += 1
    return store.finish_run(run_id)


def _measured_execute(
    store: RunStore,
    execute: OriginExecutor,
    lease,
    timeout_seconds: float,
    lease_seconds: int,
    resource_cost: ResourceCostStore | None,
    heartbeat: Callable[[], None] | None,
) -> OriginOutput:
    started = time.perf_counter()
    cpu_started = time.process_time()
    output = None
    try:
        output = _bounded_execute(
            store, execute, lease, timeout_seconds, lease_seconds, heartbeat
        )
        return output
    finally:
        if resource_cost is not None:
            wall = Decimal(str(time.perf_counter() - started))
            cpu = Decimal(str(max(0.0, time.process_time() - cpu_started)))
            usages = list(output.resources if output is not None else ())
            if not any(item.metric == ResourceMetric.INFERENCE_SECONDS for item in usages):
                usages.append(
                    ResourceUsage(ResourceMetric.INFERENCE_SECONDS, wall, "worker_total")
                )
            usages.append(ResourceUsage(ResourceMetric.CPU_SECONDS, cpu, "process_cpu"))
            peak = _peak_memory_bytes()
            if peak is not None:
                usages.append(
                    ResourceUsage(
                        ResourceMetric.PEAK_MEMORY_BYTES,
                        Decimal(peak),
                        "process_peak_working_set",
                    )
                )
            resource_cost.record_attempt(
                lease.run_id,
                lease.origin.origin_date,
                lease.attempt,
                tuple(usages),
            )


def _peak_memory_bytes() -> int | None:
    """標準ライブラリだけで取得できるprocess peak。取得不可なら未計測とする。"""
    try:
        import os

        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            get_process = ctypes.windll.kernel32.GetCurrentProcess
            get_process.restype = wintypes.HANDLE
            get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
            get_memory.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(Counters),
                wintypes.DWORD,
            ]
            get_memory.restype = wintypes.BOOL
            handle = get_process()
            if not get_memory(
                handle, ctypes.byref(counters), counters.cb
            ):
                return None
            return int(counters.PeakWorkingSetSize)
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if os.uname().sysname == "Darwin" else value * 1024
    except (AttributeError, ImportError, OSError, ValueError):
        return None


def _bounded_execute(
    store: RunStore,
    execute: OriginExecutor,
    lease,
    timeout_seconds: float,
    lease_seconds: int,
    heartbeat: Callable[[], None] | None = None,
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
            if heartbeat is not None:
                heartbeat()
    if ok:
        return value
    raise value
