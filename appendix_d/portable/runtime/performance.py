"""Local process measurements; no business rows or external telemetry."""

import ctypes
import json
import os
import platform
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime


def memory_mb():
    if os.name != "nt":
        try:
            with open("/proc/self/statm") as stream:
                return int(stream.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1024**2
        except (OSError, ValueError):
            return None
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak",
                "working",
                "paged_peak",
                "paged",
                "nonpaged_peak",
                "nonpaged",
                "page",
                "page_peak",
            )
        ]

    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return counters.working / 1024**2
    return None


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


def total_memory_mb():
    if os.name == "nt":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
                (name, ctypes.c_uint64)
                for name in (
                    "total",
                    "available",
                    "total_page",
                    "available_page",
                    "total_virtual",
                    "available_virtual",
                    "extended",
                )
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.total / 1024**2
    else:
        try:
            return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024**2
        except (ValueError, OSError):
            pass
    return None


@contextmanager
def measure(path, *, stage, details=None):
    started, cpu = time.perf_counter(), time.process_time()
    initial = memory_mb()
    samples = [initial] if initial is not None else []
    stop = threading.Event()
    info = {
        "stage": stage,
        "status": "RUNNING",
        "started_at": datetime.now(UTC).isoformat(),
        "logical_cpus": os.cpu_count(),
        "platform": platform.system(),
        "total_memory_mb": total_memory_mb(),
        "measurement_scope": "whole_server_process_sampled_250ms",
        **(details or {}),
    }
    write_json(path, info)

    def sample():
        while not stop.wait(0.25):
            value = memory_mb()
            if value is not None:
                samples.append(value)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    try:
        yield info
        if info["status"] == "RUNNING":
            info["status"] = "SUCCEEDED"
    except BaseException:
        info["status"] = "FAILED"
        raise
    finally:
        stop.set()
        thread.join(timeout=1)
        final = memory_mb()
        if final is not None:
            samples.append(final)
        info.update(
            elapsed_seconds=round(time.perf_counter() - started, 3),
            process_cpu_seconds=round(time.process_time() - cpu, 3),
            initial_rss_mb=initial,
            peak_rss_mb=max(samples) if samples else None,
        )
        write_json(path, info)
