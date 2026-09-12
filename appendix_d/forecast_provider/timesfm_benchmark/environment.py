"""TimesFMベンチマーク実行環境とLinux cgroup上限の取得。"""

from __future__ import annotations

import importlib.metadata
import os
import platform
from pathlib import Path
from typing import Any


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _read_text(paths: tuple[Path, ...]) -> str | None:
    for path in paths:
        try:
            return path.read_text(encoding="ascii").strip()
        except OSError:
            continue
    return None


def _cgroup_cpu_limit() -> float | None:
    cpu_max = _read_text((Path("/sys/fs/cgroup/cpu.max"),))
    if cpu_max:
        parts = cpu_max.split()
        try:
            if len(parts) == 2 and parts[0] != "max" and int(parts[1]) > 0:
                return int(parts[0]) / int(parts[1])
        except ValueError:
            pass
    quota = _read_text((Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"),))
    period = _read_text((Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us"),))
    try:
        if quota and period and int(quota) > 0 and int(period) > 0:
            return int(quota) / int(period)
    except ValueError:
        pass
    return None


def _cgroup_memory_limit() -> int | None:
    value = _read_text(
        (
            Path("/sys/fs/cgroup/memory.max"),
            Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
        )
    )
    if value and value != "max":
        try:
            parsed = int(value)
        except ValueError:
            return None
        # v1は無制限を非常に大きな整数で表す。
        return None if parsed >= 1 << 60 else parsed
    return None


def runtime_environment() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "timesfm_version": _package_version("timesfm"),
        "torch_version": _package_version("torch"),
        "logical_cpu_count": os.cpu_count(),
        "cgroup_cpu_limit": _cgroup_cpu_limit(),
        "cgroup_memory_limit_bytes": _cgroup_memory_limit(),
    }
