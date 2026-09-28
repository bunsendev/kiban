"""管理者が置いた条件を使い、現場担当者向けにShadow結果を整理する。"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from zoneinfo import ZoneInfo

from ..expiry_simulation import ExpirySimulationBlocked
from ..warehouse_projection import ProjectionBlocked
from .freshness import FreshnessPolicy
from .improvement_events import ImprovementEventLedger
from .inbox_ledger import InboxLedger
from .inbox_policy import InboxPolicyError, load_inbox_policy
from .learning_service import LearningService
from .local_setting_service import LocalSettingService
from .local_setting_store import LocalSettingStore

logger = logging.getLogger("kiban.field_pilot")
MAX_CONFIG_BYTES = 65_536
REQUIRED_TEXT = (
    "pilot_scope_version", "identity_bridge_version", "forecast_run_id",
    "policy_confirmed_by", "policy_reason", "policy_confirmed_at",
)


class FieldPilotReadService:
    def __init__(
        self, shadow_service, config_path: Path,
        inbox_policy_path: Path | None = None, inbox_root: Path | None = None,
        learning_admin_token: str | None = None,
        learning_operator_id: str = "FIELD_PILOT_OPERATOR",
        local_settings_dir: Path | None = None,
        local_backup_dir: Path | None = None,
    ):
        self.shadow_service = shadow_service
        self.config_path = config_path
        self.inbox_policy_path = inbox_policy_path
        self.inbox_root = inbox_root
        self.learning_admin_token = learning_admin_token
        self.learning_operator_id = learning_operator_id
        self.local_settings_dir = local_settings_dir or config_path.parent
        self.local_backup_dir = local_backup_dir
        self._local_settings = None
        self.learning = (
            LearningService(inbox_root, inbox_policy_path)
            if inbox_root is not None and inbox_policy_path is not None else None
        )
        self.improvement_events = (
            ImprovementEventLedger(inbox_root / "improvement-events.sqlite3")
            if inbox_root is not None else None
        )

    @property
    def local_settings(self) -> LocalSettingService:
        if self._local_settings is None:
            try:
                application_version = version("bunsen-forecast-provider")
            except PackageNotFoundError:
                application_version = "unpackaged"
            store = LocalSettingStore(self.local_settings_dir / "field-settings.sqlite3")
            self._local_settings = LocalSettingService(
                store, application_version, backup_root=self.local_backup_dir,
            )
        return self._local_settings

    def _observe(self, event_type: str, outcome: str, *, error_code: str | None = None,
                 metrics: dict | None = None, **identifiers) -> None:
        if self.improvement_events is None:
            return
        try:
            self.improvement_events.append(
                event_type, outcome=outcome,
                business_date=datetime.now(ZoneInfo("Asia/Tokyo")).date(),
                error_code=error_code, metrics=metrics, **identifiers,
            )
        except (OSError, ValueError, sqlite3.DatabaseError):
            logger.warning("field pilot improvement event unavailable")

    def learning_view(self) -> dict:
        return self.learning.pending_view() if self.learning else {
            "pending_count": 0, "candidates": [],
        }

    def inbox_view(self) -> dict:
        if self.inbox_policy_path is None or self.inbox_root is None:
            return {"status": "NOT_CONFIGURED", "message": "投入先を準備中です。"}
        try:
            policy = load_inbox_policy(self.inbox_policy_path)
            target_date = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
            if not (self.inbox_root / "inbox.sqlite3").is_file():
                return {
                    "status": "MISSING_OR_REVIEW", "target_date": target_date,
                    "required": [
                        {"kind": item.kind, "location_id": item.location_id,
                         "display_name": item.display_name, "status": "MISSING",
                         "freshness": "MISSING", "last_accepted_at": None}
                        for item in policy.required
                    ],
                    "checked_count": 0, "processed_count": 0,
                    "received_count": 0, "review_count": 0,
                    "duplicate_count": 0, "last_updated_at": None,
                }
            return InboxLedger(self.inbox_root / "inbox.sqlite3").summary(policy, target_date)
        except (InboxPolicyError, OSError, ValueError, sqlite3.DatabaseError):
            logger.warning("field pilot inbox unavailable")
            return {
                "status": "SETUP_REQUIRED",
                "message": "投入先の設定を管理担当者へご確認ください。",
            }

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
            settings = self._settings()
            if self.inbox_policy_path is not None:
                FreshnessPolicy.from_settings(settings)
        except (ValueError, OSError, json.JSONDecodeError):
            return False
        return True

    def view(self) -> dict:
        if self.inbox_policy_path is not None:
            inbox = self.inbox_view()
            if inbox["status"] != "READY":
                self._observe("VIEW_BLOCKED", "BLOCKED", error_code="INBOX_NOT_READY")
                return {
                    "status": "DATA_NOT_READY", "mode": "SHADOW", "read_only": True,
                    "message": "本日の必要データが揃っていません。投入状況をご確認ください。",
                }
        try:
            settings = self._settings()
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            logger.warning("field pilot configuration unavailable: %s", type(exc).__name__)
            self._observe("VIEW_BLOCKED", "BLOCKED", error_code="SETUP_REQUIRED")
            return {
                "status": "SETUP_REQUIRED", "mode": "SHADOW", "read_only": True,
                "message": "起動準備に問題があります。管理担当者へご連絡ください。",
            }
        if self.inbox_policy_path is not None:
            try:
                freshness_policy = FreshnessPolicy.from_settings(settings)
            except ValueError:
                self._observe("VIEW_BLOCKED", "BLOCKED", error_code="FRESHNESS_POLICY_MISSING")
                return {
                    "status": "SETUP_REQUIRED", "mode": "SHADOW", "read_only": True,
                    "message": "鮮度条件の設定を管理担当者へご確認ください。",
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
            self._observe("VIEW_BLOCKED", "BLOCKED", error_code="DATA_NOT_READY")
            return {
                "status": "DATA_NOT_READY", "mode": "SHADOW", "read_only": True,
                "message": "データを表示できません。管理担当者へご連絡ください。",
            }
        if self.inbox_policy_path is not None:
            freshness_error = freshness_policy.check(result.get("snapshot_at"), datetime.now(UTC))
            if freshness_error:
                self._observe("VIEW_BLOCKED", "BLOCKED", error_code=freshness_error,
                              policy_version=freshness_policy.version)
                return {
                    "status": "DATA_NOT_READY", "mode": "SHADOW", "read_only": True,
                    "message": "在庫データの日時を確認中です。管理担当者へご連絡ください。",
                }
        self._observe(
            "VIEW_READY", "OK", metrics={"item_count": len(result["rows"])},
            forecast_run_id=result["forecast_run_id"],
            inventory_snapshot_id=result["inventory_snapshot_id"],
        )
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
