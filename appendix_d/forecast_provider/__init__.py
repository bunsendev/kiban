"""予測プロバイダー共通インターフェース（BUNSEN-FCST-IMPL-002 付録D v2.9）。"""

from .contracts import (
    ContextRef,
    ForecastDataset,
    ForecastProvider,
    ModelMetadata,
    ModelRef,
    ProviderCapabilities,
    ProviderConfig,
    ProviderMetadata,
    RunContext,
    ValidationIssue,
    ValidationResult,
)
from .errors import (
    ContractViolationError,
    InsufficientHistoryError,
    NonRetryableProviderError,
    ProviderError,
    RetryableProviderError,
    TimeoutProviderError,
)
from .registry import ProviderRegistry, registry

__all__ = [
    "ContextRef",
    "ContractViolationError",
    "ForecastDataset",
    "ForecastProvider",
    "InsufficientHistoryError",
    "ModelMetadata",
    "ModelRef",
    "NonRetryableProviderError",
    "ProviderCapabilities",
    "ProviderConfig",
    "ProviderError",
    "ProviderMetadata",
    "ProviderRegistry",
    "RetryableProviderError",
    "RunContext",
    "TimeoutProviderError",
    "ValidationIssue",
    "ValidationResult",
    "registry",
]
