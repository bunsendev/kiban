"""ファイル名日付を正式なsnapshot日時へ変換する版付きpolicy。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import PurePath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import SnapshotAtSourceKind

_FILENAME_DATE = re.compile(r"_(\d{8})\.csv$", re.IGNORECASE)


@dataclass(frozen=True)
class SnapshotTimePolicy:
    policy_version: str
    content_sha256: str
    source_kind: SnapshotAtSourceKind
    cutoff_time: time
    timezone_name: str
    created_by: str
    reason: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "policy_version",
            "content_sha256",
            "timezone_name",
            "created_by",
            "reason",
        ):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name}は必須です")
            object.__setattr__(self, name, value)
        if len(self.content_sha256) != 64:
            raise ValueError("content_sha256は64文字です")
        if self.source_kind is not SnapshotAtSourceKind.FILENAME_YYYYMMDD:
            raise ValueError("snapshot time policyはFILENAME_YYYYMMDD専用です")
        if self.cutoff_time.tzinfo is not None or self.cutoff_time.microsecond:
            raise ValueError("cutoff_timeはtimezoneなし・秒精度で指定してください")
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone_nameは有効なIANA timezoneです") from exc
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_atはtimezone付き日時で指定してください")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))

    def resolve(self, source_reference: str) -> datetime:
        name = PurePath(source_reference.replace("\\", "/")).name
        match = _FILENAME_DATE.search(name)
        if match is None:
            raise ValueError("source filenameがYYYYMMDD規則に一致しません")
        try:
            source_date = datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError as exc:
            raise ValueError("source filenameの日付が不正です") from exc
        timezone = ZoneInfo(self.timezone_name)
        local = datetime.combine(source_date, self.cutoff_time, timezone)
        if local.astimezone(UTC).astimezone(timezone).replace(fold=0) != local.replace(fold=0):
            raise ValueError("指定日時はtimezone上に存在しません")
        if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
            raise ValueError("指定日時はtimezone上で一意ではありません")
        return local.astimezone(UTC)


def build_snapshot_time_policy(
    *,
    cutoff_time: time,
    timezone_name: str,
    created_by: str,
    reason: str,
    created_at: datetime,
) -> SnapshotTimePolicy:
    payload = {
        "format": "inventory-snapshot-time-policy-v1",
        "filename_pattern": "_(YYYYMMDD).csv",
        "source_kind": SnapshotAtSourceKind.FILENAME_YYYYMMDD.value,
        "cutoff_time": cutoff_time.isoformat(),
        "timezone_name": timezone_name.strip(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SnapshotTimePolicy(
        f"inventory-snapshot-time-policy-{digest}",
        digest,
        SnapshotAtSourceKind.FILENAME_YYYYMMDD,
        cutoff_time,
        timezone_name,
        created_by,
        reason,
        created_at,
    )
