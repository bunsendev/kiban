"""倉庫だけを対象とするShadow参考補充量の明示的な計算契約。"""

from .domain import (
    FieldReferencePolicy,
    ReferenceQuantity,
    build_reference_policy,
    calculate_reference_quantity,
)
from .service import FieldReferenceBatchService

__all__ = [
    "FieldReferenceBatchService",
    "FieldReferencePolicy",
    "ReferenceQuantity",
    "build_reference_policy",
    "calculate_reference_quantity",
]
