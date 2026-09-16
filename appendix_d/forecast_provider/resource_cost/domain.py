"""資源計測・単価の決定的IDと入力検証。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from .contracts import ResourceMeasurement, ResourceMetric, ResourceUsage, UnitPrice


def _digest(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_measurement(
    run_id: str,
    origin_date: date,
    attempt: int,
    usage: ResourceUsage,
    measured_at: datetime | None = None,
) -> ResourceMeasurement:
    if not run_id or attempt <= 0:
        raise ValueError("run_idと正のattemptが必要です")
    # artifact等の明示identityはrun内で一度だけ数える。通常の時間計測は試行単位。
    key = {
        "run_id": run_id,
        "metric": usage.metric.value,
        "identity": usage.identity,
    }
    if usage.identity is None:
        key.update(
            {
                "origin_date": origin_date.isoformat(),
                "attempt": attempt,
                "source": usage.source,
            }
        )
    measurement_id = _digest(key)
    return ResourceMeasurement(
        measurement_id,
        run_id,
        origin_date,
        attempt,
        usage.metric,
        usage.metric.unit,
        usage.quantity,
        usage.source,
        usage.identity,
        measured_at or datetime.now(UTC),
    )


def make_unit_price(
    *,
    provider_id: str,
    metric: ResourceMetric,
    unit_price: Decimal,
    currency: str,
    retrieved_on: date,
    source_ref: str,
    created_by: str,
    created_at: datetime | None = None,
) -> UnitPrice:
    provider_id = provider_id.strip()
    currency = currency.strip().upper()
    if not provider_id:
        raise ValueError("provider_idは空にできません")
    if not unit_price.is_finite() or unit_price < 0:
        raise ValueError("単価は有限の0以上です")
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("currencyは3文字の通貨コードです")
    if not source_ref.strip() or not created_by.strip():
        raise ValueError("単価の参照元と登録者が必要です")
    identity = {
        "provider_id": provider_id,
        "metric": metric.value,
        "unit": metric.unit,
        "unit_price": str(unit_price),
        "currency": currency,
        "retrieved_on": retrieved_on.isoformat(),
        "source_ref": source_ref.strip(),
        "created_by": created_by.strip(),
    }
    return UnitPrice(
        _digest(identity),
        provider_id,
        metric,
        metric.unit,
        unit_price,
        currency,
        retrieved_on,
        source_ref.strip(),
        created_by.strip(),
        created_at or datetime.now(UTC),
    )
