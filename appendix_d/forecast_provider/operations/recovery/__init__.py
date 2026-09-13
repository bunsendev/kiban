"""隔離PostgreSQLリカバリ訓練。"""

from .contracts import DrillResult
from .runner import run_recovery_drill

__all__ = ["DrillResult", "run_recovery_drill"]
