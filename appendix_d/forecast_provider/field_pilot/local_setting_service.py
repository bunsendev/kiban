"""JANと在庫基準時刻の現場変更を検証し、旧版を残して適用する。"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..inventory_foundation.domain import validate_jan
from .local_setting_backup import LocalSettingBackup
from .local_setting_store import LocalSettingStore

PRODUCT = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
ACTOR = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
LOCAL_TIME = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
PRECISIONS = {"EXACT_TIME", "BUSINESS_DAY", "END_OF_DAY", "START_OF_DAY"}
TIME_SOURCES = {
    "MORNING", "PREVIOUS_CLOSE", "FILE_CREATED", "DAILY_CLOSE", "SPECIFIED", "OTHER",
}
REASONS = {"INITIAL_CONFIRMATION", "CORRECTION", "BUSINESS_RULE_CHANGE", "ROLLBACK"}


class LocalSettingService:
    def __init__(self, store: LocalSettingStore, application_version: str,
                 before_change=None, backup_root: Path | None = None):
        self.store = store
        self.application_version = application_version
        data_root = (
            store.path.parent.parent
            if store.path.parent.name == "Config" else store.path.parent
        )
        self.before_change = before_change or LocalSettingBackup(
            store.path, backup_root or data_root / "Backup",
        ).create

    @staticmethod
    def _validate(change_type: str, target: str, value: dict) -> None:
        if change_type == "JAN_MAPPING":
            if (not PRODUCT.fullmatch(target) or not isinstance(value, dict)
                    or set(value) != {"jan", "product_name"}):
                raise ValueError("JAN_MAPPING_INVALID")
            if not isinstance(value["jan"], str):
                raise ValueError("JAN_MAPPING_INVALID")
            validate_jan(value["jan"])
            name = value["product_name"]
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
                raise ValueError("JAN_MAPPING_INVALID")
        elif change_type == "INVENTORY_TIME_POLICY":
            if (target != "WAREHOUSE" or not isinstance(value, dict)
                    or not {"source", "precision", "time_zone"}.issubset(value)
                    or set(value) - {"source", "precision", "time_zone", "local_time"}):
                raise ValueError("INVENTORY_TIME_POLICY_INVALID")
            if (not isinstance(value["source"], str)
                    or not isinstance(value["precision"], str)
                    or value["source"] not in TIME_SOURCES
                    or value["precision"] not in PRECISIONS
                    or value["time_zone"] != "Asia/Tokyo"):
                raise ValueError("INVENTORY_TIME_POLICY_INVALID")
            local_time = value.get("local_time")
            if value["precision"] == "EXACT_TIME":
                if (value["source"] != "SPECIFIED" or not isinstance(local_time, str)
                        or not LOCAL_TIME.fullmatch(local_time)):
                    raise ValueError("EXACT_TIME_SOURCE_REQUIRED")
            elif local_time is not None:
                raise ValueError("INVENTORY_TIME_POLICY_INVALID")
        elif change_type == "SHIPMENT_TRIAL_POLICY":
            if (not PRODUCT.fullmatch(target) or not isinstance(value, dict)
                    or set(value) != {"unit", "missing_day"}
                    or value["unit"] not in {"CASE", "BUNDLE", "PALLET", "MIXED", "UNKNOWN"}
                    or value["missing_day"] not in {
                        "OBSERVED_ONLY", "ZERO_WHEN_DAILY_FILE_PRESENT",
                    }):
                raise ValueError("SHIPMENT_TRIAL_POLICY_INVALID")
        else:
            raise ValueError("LOCAL_SETTING_TYPE_INVALID")

    def change(self, *, change_type: str, target: str, value: dict,
               effective_from: date, actor: str, reason_code: str, comment: str,
               expected_version: str | None, now: datetime | None = None,
               rollback_of: str | None = None) -> dict:
        observed = now or datetime.now(UTC)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("LOCAL_SETTING_TIME_INVALID")
        if not ACTOR.fullmatch(actor) or reason_code not in REASONS:
            raise ValueError("LOCAL_SETTING_ACTOR_OR_REASON_INVALID")
        if not isinstance(comment, str) or len(comment) > 500:
            raise ValueError("LOCAL_SETTING_COMMENT_INVALID")
        if effective_from < observed.astimezone(ZoneInfo("Asia/Tokyo")).date():
            raise ValueError("LOCAL_SETTING_RETROACTIVE_CHANGE")
        self._validate(change_type, target, value)
        if self.before_change is not None:
            self.before_change()
        return self.store.append(
            change_type=change_type, target=target, value=value,
            effective_from=effective_from, actor=actor, reason_code=reason_code,
            comment=comment, application_version=self.application_version,
            expected_version=expected_version, rollback_of=rollback_of, changed_at=observed,
        )

    def restore_previous(self, *, version: str, actor: str, expected_version: str,
                         comment: str, now: datetime | None = None) -> dict:
        previous = self.store.version(version)
        if previous is None:
            raise ValueError("LOCAL_SETTING_VERSION_NOT_FOUND")
        return self.change(
            change_type=previous["change_type"], target=previous["target"],
            value=previous["value"], effective_from=(now or datetime.now(UTC)).astimezone(
                ZoneInfo("Asia/Tokyo")
            ).date(),
            actor=actor, reason_code="ROLLBACK", comment=comment,
            expected_version=expected_version, now=now, rollback_of=version,
        )
