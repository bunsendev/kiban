"""Windows build-PC smoke test for the frozen server; no Docker or Python inside app."""

import argparse
import ctypes
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def process_metrics(pid: int) -> dict:
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

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenProcess failed")
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        created = ctypes.c_uint64()
        exited = ctypes.c_uint64()
        kernel_time = ctypes.c_uint64()
        user_time = ctypes.c_uint64()
        if not kernel.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            raise OSError(ctypes.get_last_error(), "GetProcessTimes failed")
        return {
            "working_set_mb": round(counters.WorkingSetSize / 1024**2, 2),
            "peak_working_set_mb": round(counters.PeakWorkingSetSize / 1024**2, 2),
            "cpu_seconds": round((kernel_time.value + user_time.value) / 10**7, 3),
        }
    finally:
        kernel.CloseHandle(handle)


def get(port: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=4) as response:
        return json.load(response)


def listening_addresses(port: int, pid: int) -> list[str]:
    text = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True, errors="replace")
    addresses = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[-1] == str(pid):
            addresses.append(parts[1].rsplit(":", 1)[0])
    return addresses


def run_once(root: Path, port: int):
    exe = root / "App" / "BunsenPortable.exe"
    process = subprocess.Popen(
        [str(exe), "--server", "--port", str(port), "--data-root", str(root / "Data")],
        cwd=exe.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
        env={**os.environ, "PORTABLE_CONTROL_TOKEN": "smoke-only"},
    )
    started = time.monotonic()
    try:
        for _ in range(150):
            if process.poll() is not None:
                raise RuntimeError(f"Frozen API exited: {process.returncode}")
            try:
                if get(port, "/ready")["ready"]:
                    return process, time.monotonic() - started
            except (OSError, urllib.error.URLError, ValueError):
                time.sleep(0.2)
        raise RuntimeError("Frozen API readiness timeout")
    except Exception:
        process.terminate()
        process.wait(timeout=10)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--port", type=int, default=48179)
    args = parser.parse_args()
    root = args.root.resolve()
    sample = (root / "Sample" / "synthetic_shipments.csv").read_bytes()
    process, startup1 = run_once(root, args.port)
    try:
        addresses = listening_addresses(args.port, process.pid)
        assert addresses == ["127.0.0.1"], addresses
        idle_metrics = process_metrics(process.pid)
        started = time.monotonic()
        request = urllib.request.Request(
            f"http://127.0.0.1:{args.port}/api/runs",
            data=sample,
            headers={"Content-Type": "text/csv"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            first = json.load(response)
        forecast_time = time.monotonic() - started
        after_forecast_metrics = process_metrics(process.pid)
        assert first["status"] == "SUCCESS"
        assert len(first["predictions"]) == 14
    finally:
        stopping = time.monotonic()
        process.terminate()
        process.wait(timeout=10)
        stop_time = time.monotonic() - stopping
    process, startup2 = run_once(root, args.port)
    try:
        history = get(args.port, "/api/runs")
        assert any(item["run_id"] == first["run_id"] for item in history)
        saved = get(args.port, f"/api/runs/{first['run_id']}")
        assert saved["result_sha256"] == first["result_sha256"]
        print(
            json.dumps(
                {
                    "startup_first_seconds": startup1,
                    "startup_second_seconds": startup2,
                    "forecast_seconds": forecast_time,
                "listening_addresses": addresses,
                    "stop_seconds": stop_time,
                    "idle": idle_metrics,
                    "after_forecast": after_forecast_metrics,
                    "data_bytes": sum(
                        p.stat().st_size for p in (root / "Data").rglob("*") if p.is_file()
                    ),
                    "run_id": first["run_id"],
                    "result_sha256": first["result_sha256"],
                },
                indent=2,
            )
        )
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
