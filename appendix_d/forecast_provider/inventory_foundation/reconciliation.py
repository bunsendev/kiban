"""CSV原本数量とcanonical bucket数量の照合contract。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class InventoryQuantityReconciliation:
    source_quantity_cases: Decimal
    normalized_quantity_cases: Decimal
    source_row_count: int
    accepted_row_count: int
    quarantined_row_count: int

    @property
    def reconciled(self) -> bool:
        return self.source_quantity_cases == self.normalized_quantity_cases
