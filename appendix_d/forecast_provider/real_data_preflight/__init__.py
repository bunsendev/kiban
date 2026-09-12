"""実データ受入前の実行環境プリフライト。"""

from .contracts import PreflightRoots
from .runner import run_preflight

__all__ = ["PreflightRoots", "run_preflight"]
