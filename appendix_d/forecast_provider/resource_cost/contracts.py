"""Provider共通の資源計測・単価台帳契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class ResourceMetric(StrEnum):
    PREPROCESSING_SECONDS = "PREPROCESSING_SECONDS"
    TRAINING_SECONDS = "TRAINING_SECONDS"
    INFERENCE_SECONDS = "INFERENCE_SECONDS"
    CPU_SECONDS = "CPU_SECONDS"
    GPU_SECONDS = "GPU_SECONDS"
    PEAK_MEMORY_BYTES = "PEAK_MEMORY_BYTES"
    MODEL_DOWNLOAD_SECONDS = "MODEL_DOWNLOAD_SECONDS"
    STORAGE_BYTES = "STORAGE_BYTES"

    @property
    def unit(self) -> str:
        return "second" if self.value.endswith("_SECONDS") else "byte"


@dataclass(frozen=True)
class ResourceUsage:
    """Executorが返す計測値。identityは同一artifact等の重複保存を防ぐ。"""

    metric: ResourceMetric
    quantity: Decimal
    source: str
    identity: str | None = None

    def __post_init__(self) -> None:
        if not self.quantity.is_finite() or self.quantity < 0:
            raise ValueError("資源計測量は有限の0以上です")
        if not self.source:
            raise ValueError("資源計測sourceは空にできません")


@dataclass(frozen=True)
class ResourceMeasurement:
    measurement_id: str
    run_id: str
    origin_date: date
    attempt: int
    metric: ResourceMetric
    unit: str
    quantity: Decimal
    source: str
    identity: str | None
    measured_at: datetime


@dataclass(frozen=True)
class UnitPrice:
    price_id: str
    provider_id: str
    metric: ResourceMetric
    unit: str
    unit_price: Decimal
    currency: str
    retrieved_on: date
    source_ref: str
    created_by: str
    created_at: datetime


class ResourceCostStore(Protocol):
    def record_attempt(
        self,
        run_id: str,
        origin_date: date,
        attempt: int,
        usages: tuple[ResourceUsage, ...],
    ) -> list[ResourceMeasurement]: ...

    def put_unit_price(self, value: UnitPrice) -> UnitPrice: ...
    def list_unit_prices(
        self, provider_id: str | None = None, metric: ResourceMetric | None = None
    ) -> list[UnitPrice]: ...
    def summarize(self, run_id: str, *, include_attempts: bool = False) -> dict | None: ...
