"""wall time、CPU time、process peak RSSの計測。"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

T = TypeVar("T")


class ProcessProbe(Protocol):
    def wall_ns(self) -> int: ...

    def cpu_ns(self) -> int: ...

    def peak_rss_bytes(self) -> int: ...


class SystemProcessProbe:
    """専用Linux Worker processの累積peak RSSを読む。"""

    def wall_ns(self) -> int:
        return time.perf_counter_ns()

    def cpu_ns(self) -> int:
        return time.process_time_ns()

    def peak_rss_bytes(self) -> int:
        try:
            import resource
        except ImportError as exc:
            raise RuntimeError("peak RSS計測はLinux Docker Workerで実行してください") from exc
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024


@dataclass(frozen=True)
class Measurement:
    wall_seconds: float
    cpu_seconds: float
    peak_rss_bytes: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "wall_seconds": self.wall_seconds,
            "cpu_seconds": self.cpu_seconds,
            "peak_rss_bytes": self.peak_rss_bytes,
        }


def measure_call(function: Callable[[], T], probe: ProcessProbe) -> tuple[T, Measurement]:
    wall_start = probe.wall_ns()
    cpu_start = probe.cpu_ns()
    result = function()
    cpu_end = probe.cpu_ns()
    wall_end = probe.wall_ns()
    measurement = Measurement(
        wall_seconds=(wall_end - wall_start) / 1_000_000_000,
        cpu_seconds=(cpu_end - cpu_start) / 1_000_000_000,
        peak_rss_bytes=probe.peak_rss_bytes(),
    )
    if measurement.wall_seconds < 0 or measurement.cpu_seconds < 0:
        raise RuntimeError("process clockが単調増加していません")
    return result, measurement
