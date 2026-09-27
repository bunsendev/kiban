"""在庫JAN/locationと需要予測canonical product/centerの版付き接続。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

from ..inventory_foundation.domain import canonical_datetime, validate_jan


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label}は必須です")
    return normalized


@dataclass(frozen=True)
class InventoryForecastBridgeRecord:
    bridge_version: str
    jan: str
    warehouse_id: str
    canonical_product_id: str
    forecast_center_id: str
    effective_from: date
    effective_to: date | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bridge_version", _required(self.bridge_version, "bridge_version"))
        object.__setattr__(self, "jan", validate_jan(self.jan))
        for name in ("warehouse_id", "canonical_product_id", "forecast_center_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_toはeffective_from以降です")


@dataclass(frozen=True)
class InventoryForecastBridgeVersion:
    bridge_version: str
    content_sha256: str
    created_by: str
    reason: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "bridge_version", _required(self.bridge_version, "bridge_version"))
        if len(self.content_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.content_sha256
        ):
            raise ValueError("content_sha256は64文字のSHA-256です")
        object.__setattr__(self, "created_by", _required(self.created_by, "created_by"))
        object.__setattr__(self, "reason", _required(self.reason, "reason"))
        canonical_datetime(self.created_at, "created_at")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


@dataclass(frozen=True)
class InventoryForecastBridge:
    version: InventoryForecastBridgeVersion
    records: tuple[InventoryForecastBridgeRecord, ...]


@dataclass(frozen=True)
class ResolvedInventoryForecastIdentity:
    jan: str
    warehouse_id: str
    canonical_product_id: str
    forecast_center_id: str
    bridge_version: str


class IdentityResolutionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def build_inventory_forecast_bridge(
    *,
    records: list[tuple[str, str, str, str, date, date | None]]
    | tuple[tuple[str, str, str, str, date, date | None], ...],
    created_by: str,
    reason: str,
    created_at: datetime,
) -> InventoryForecastBridge:
    created_by = _required(created_by, "created_by")
    reason = _required(reason, "reason")
    canonical_datetime(created_at, "created_at")
    normalized = []
    for jan, warehouse, canonical_id, center_id, effective_from, effective_to in records:
        if effective_to is not None and effective_to < effective_from:
            raise ValueError("effective_toはeffective_from以降です")
        normalized.append(
            (
                validate_jan(jan),
                _required(warehouse, "warehouse_id"),
                _required(canonical_id, "canonical_product_id"),
                _required(center_id, "forecast_center_id"),
                effective_from,
                effective_to,
            )
        )
    normalized.sort(key=lambda item: tuple("" if value is None else str(value) for value in item))
    if not normalized:
        raise ValueError("identity bridgeには1件以上必要です")
    if len(normalized) != len(set(normalized)):
        raise ValueError("identity bridge recordが重複しています")
    payload = {
        "format_version": "inventory-forecast-bridge-v1",
        "created_by": created_by,
        "reason": reason,
        "records": [
            {
                "jan": item[0],
                "warehouse_id": item[1],
                "canonical_product_id": item[2],
                "forecast_center_id": item[3],
                "effective_from": item[4].isoformat(),
                "effective_to": None if item[5] is None else item[5].isoformat(),
            }
            for item in normalized
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    version_id = f"inventory-forecast-bridge-{digest}"
    version = InventoryForecastBridgeVersion(version_id, digest, created_by, reason, created_at)
    return InventoryForecastBridge(
        version,
        tuple(InventoryForecastBridgeRecord(version_id, *item) for item in normalized),
    )


def resolve_identity(
    bridge: InventoryForecastBridge,
    *,
    jan: str,
    warehouse_id: str,
    business_date: date,
    known_at: datetime,
) -> ResolvedInventoryForecastIdentity:
    canonical_datetime(known_at, "known_at")
    if bridge.version.created_at > known_at.astimezone(UTC):
        raise IdentityResolutionError(
            "BRIDGE_NOT_KNOWN_AS_OF", "指定known_at時点ではidentity bridgeを利用できません"
        )
    normalized_jan = validate_jan(jan)
    normalized_warehouse = _required(warehouse_id, "warehouse_id")
    candidates = [
        value
        for value in bridge.records
        if value.jan == normalized_jan
        and value.warehouse_id == normalized_warehouse
        and value.effective_from <= business_date
        and (value.effective_to is None or business_date <= value.effective_to)
    ]
    if not candidates:
        raise IdentityResolutionError("IDENTITY_MISSING", "有効な予測・在庫identityがありません")
    identities = {(value.canonical_product_id, value.forecast_center_id) for value in candidates}
    if len(identities) != 1:
        raise IdentityResolutionError("IDENTITY_AMBIGUOUS", "予測・在庫identityが複数候補です")
    canonical_product_id, forecast_center_id = next(iter(identities))
    return ResolvedInventoryForecastIdentity(
        normalized_jan,
        normalized_warehouse,
        canonical_product_id,
        forecast_center_id,
        bridge.version.bridge_version,
    )
