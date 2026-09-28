"""管理者が置いた条件を使い、現場担当者向けにShadow結果を整理する。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from ..expiry_simulation import ExpirySimulationBlocked
from ..warehouse_projection import ProjectionBlocked

logger = logging.getLogger("kiban.field_pilot")
MAX_CONFIG_BYTES = 65_536
REQUIRED_TEXT = (
    "pilot_scope_version", "identity_bridge_version", "forecast_run_id",
    "policy_confirmed_by", "policy_reason", "policy_confirmed_at",
)


class FieldPilotReadService:
    def __init__(self, shadow_service, config_path: Path):
        self.shadow_service = shadow_service
        self.config_path = config_path

    def _settings(self) -> dict:
        if not self.config_path.is_file() or self.config_path.is_symlink():
            raise ValueError("FIELD_PILOT_CONFIG_MISSING")
        if self.config_path.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError("FIELD_PILOT_CONFIG_TOO_LARGE")
        settings = json.loads(self.config_path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise ValueError("FIELD_PILOT_CONFIG_INVALID")
        if settings.get("mode") != "SHADOW" or settings.get("read_only") is not True:
            raise ValueError("FIELD_PILOT_MODE_INVALID")
        if settings.get("environment") != "FIELD_PILOT":
            raise ValueError("FIELD_PILOT_ENVIRONMENT_INVALID")
        for key in REQUIRED_TEXT:
            if not isinstance(settings.get(key), str) or not settings[key].strip():
                raise ValueError("FIELD_PILOT_CONFIG_INCOMPLETE")
        for key in ("minimum_remaining_days", "attention_days"):
            value = settings.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 365:
                raise ValueError("FIELD_PILOT_CONFIG_INCOMPLETE")
        confirmed_at = datetime.fromisoformat(settings["policy_confirmed_at"])
        if confirmed_at.tzinfo is None or confirmed_at.utcoffset() is None:
            raise ValueError("FIELD_PILOT_CONFIG_TIME_INVALID")
        settings["policy_confirmed_at"] = confirmed_at
        for key in ("product_labels", "warehouse_labels"):
            labels = settings.get(key, {})
            if not isinstance(labels, dict) or any(
                not isinstance(label, str) or not isinstance(value, str)
                or len(value) > 120 for label, value in labels.items()
            ):
                raise ValueError("FIELD_PILOT_LABELS_INVALID")
            settings[key] = labels
        return settings

    def config_ready(self) -> bool:
        try:
            self._settings()
        except (ValueError, OSError, json.JSONDecodeError):
            return False
        return True

    def view(self) -> dict:
        try:
            settings = self._settings()
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            logger.warning("field pilot configuration unavailable: %s", type(exc).__name__)
            return {
                "status": "SETUP_REQUIRED", "mode": "SHADOW", "read_only": True,
                "message": "起動準備に問題があります。管理担当者へご連絡ください。",
            }
        try:
            result = self.shadow_service.preview(
                calculation_at=datetime.now(UTC),
                pilot_scope_version=settings["pilot_scope_version"],
                identity_bridge_version=settings["identity_bridge_version"],
                forecast_run_id=settings["forecast_run_id"],
                minimum_remaining_days=settings["minimum_remaining_days"],
                attention_days=settings["attention_days"],
                policy_confirmed_by=settings["policy_confirmed_by"],
                policy_reason=settings["policy_reason"],
                policy_confirmed_at=settings["policy_confirmed_at"],
            )
        except (ProjectionBlocked, ExpirySimulationBlocked, ValueError) as exc:
            logger.warning(
                "field pilot data unavailable: %s", getattr(exc, "code", type(exc).__name__)
            )
            return {
                "status": "DATA_NOT_READY", "mode": "SHADOW", "read_only": True,
                "message": "データを表示できません。管理担当者へご連絡ください。",
            }
        rows = []
        for item in result["rows"]:
            rows.append({
                "product": settings["product_labels"].get(item["jan"], f"JAN {item['jan']}"),
                "warehouse": settings["warehouse_labels"].get(
                    item["warehouse_id"], item["warehouse_id"]
                ),
                "jan": item["jan"],
                "warehouse_id": item["warehouse_id"],
                "current_warehouse_cases": item["current_warehouse_cases"],
                "forecast_7_days_cases": item["forecast_7_days_cases"],
                "forecast_14_days_cases": item["forecast_14_days_cases"],
                "first_shortage_date": item["first_gross_shortage_date"],
                "expiry_attention_cases": item["attention_after_first_day_cases"],
                "expiry_unconsumed_cases": item["unconsumed_by_cutoff_14_days_cases"],
                "days": item["days"],
                "expiry_buckets": item["expiry_buckets"],
            })
        return {
            "status": "READY", "mode": "SHADOW", "read_only": True,
            "message": "試験運用中。現在の業務判断を変更せず、参考情報として確認してください。",
            "data_updated_at": result["snapshot_at"],
            "calculated_at": result["calculation_at"],
            "summary": {
                "item_count": len(rows),
                "shortage_count": sum(row["first_shortage_date"] is not None for row in rows),
                "expiry_attention_count": sum(
                    row["expiry_attention_cases"] != "0"
                    or row["expiry_unconsumed_cases"] != "0" for row in rows
                ),
            },
            "rows": rows,
            "admin": {
                "inventory_snapshot_id": result["inventory_snapshot_id"],
                "pilot_scope_version": result["pilot_scope_version"],
                "identity_bridge_version": result["identity_bridge_version"],
                "forecast_run_id": result["forecast_run_id"],
                "expiry_policy_version": result["policy_version"],
            },
        }
