"""Field Pilotの表示前に、承認済みの鮮度条件を適用する。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class FreshnessPolicy:
    version: str
    max_snapshot_age_hours: int

    @classmethod
    def from_settings(cls, settings: dict) -> FreshnessPolicy:
        raw = settings.get("freshness_policy")
        if not isinstance(raw, dict):
            raise ValueError("FRESHNESS_POLICY_MISSING")
        version = raw.get("version")
        hours = raw.get("max_snapshot_age_hours")
        if not isinstance(version, str) or not version.strip() or len(version) > 120:
            raise ValueError("FRESHNESS_POLICY_INVALID")
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 168:
            raise ValueError("FRESHNESS_POLICY_INVALID")
        return cls(version.strip(), hours)

    def check(self, snapshot_at: str, now: datetime) -> str | None:
        try:
            snapshot = datetime.fromisoformat(snapshot_at)
        except (TypeError, ValueError):
            return "SNAPSHOT_TIME_INVALID"
        if snapshot.tzinfo is None or snapshot.utcoffset() is None:
            return "SNAPSHOT_TIME_INVALID"
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("NOW_TIME_INVALID")
        if snapshot > now:
            return "SNAPSHOT_IN_FUTURE"
        if snapshot.astimezone(JST).date() != now.astimezone(JST).date():
            return "SNAPSHOT_BUSINESS_DATE_MISMATCH"
        if (now - snapshot).total_seconds() > self.max_snapshot_age_hours * 3600:
            return "SNAPSHOT_TOO_OLD"
        return None
