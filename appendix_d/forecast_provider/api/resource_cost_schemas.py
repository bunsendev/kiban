"""資源単価APIの入力契約。"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from ..resource_cost import ResourceMetric


class UnitPriceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(default="*", min_length=1)
    metric: ResourceMetric
    unit_price: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    retrieved_on: date
    source_ref: str = Field(min_length=1)
    created_by: str | None = Field(default=None, min_length=1)
