"""Content identities for immutable Portable inventory contracts."""

import hashlib
import json
from dataclasses import asdict
from datetime import date
from enum import Enum

from forecast_provider.inventory_foundation import InventoryInputMappingVersion


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def location_identity(locations: list[dict], effective_dates: dict[str, date]) -> tuple[str, str]:
    # Include every persisted field: effective dates must not collide across daily intakes.
    contract = sorted(
        (
            {
                "location_id": item["location_id"],
                "location_code": item["location_code"],
                "location_name": item["location_name"],
                "location_type": "WAREHOUSE",
                "effective_from": effective_dates[item["source_center"]].isoformat(),
                "effective_to": None,
            }
            for item in locations
        ),
        key=lambda item: (item["location_code"], item["location_id"]),
    )
    digest = _digest(contract)
    return "portable-locations-v2-" + digest, digest


def mapping_identity(mapping: InventoryInputMappingVersion) -> str:
    # Audit metadata may differ on retry; the immutable data contract may not.
    ignored = {"mapping_version", "created_by", "reason", "created_at"}
    contract = {
        key: value.value if isinstance(value, Enum) else value
        for key, value in asdict(mapping).items()
        if key not in ignored
    }
    return "portable-inventory-map-v2-" + _digest(contract)
