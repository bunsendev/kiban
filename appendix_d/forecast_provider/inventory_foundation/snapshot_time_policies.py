"""確認済みsnapshot時刻policy CSVの決定的な正式取込。"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from .contracts import SnapshotAtSourceKind
from .snapshot_time import SnapshotTimePolicy, build_snapshot_time_policy

SNAPSHOT_TIME_POLICY_HEADER = ["日付取得方式", "締め時刻", "timezone", "確認メモ"]
CONFIRMED_NOTE = "確認済み"
MAX_SNAPSHOT_TIME_POLICY_BYTES = 64 * 1024


def parse_confirmed_snapshot_time_policy_csv(
    content: bytes,
    *,
    created_by: str,
    reason: str,
    created_at: datetime,
) -> SnapshotTimePolicy:
    if not content or len(content) > MAX_SNAPSHOT_TIME_POLICY_BYTES:
        raise ValueError("snapshot時刻policyは1 byte以上64 KiB以下にしてください")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        if reader.fieldnames != SNAPSHOT_TIME_POLICY_HEADER:
            raise ValueError("snapshot時刻policyの列がtemplateと一致しません")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("snapshot時刻policyはUTF-8 CSVで保存してください") from exc
    if len(rows) != 1:
        raise ValueError("snapshot時刻policyは1行で指定してください")
    row = rows[0]
    if (row.get("確認メモ") or "").strip() != CONFIRMED_NOTE:
        raise ValueError("確認メモを確認済みにしてください")
    if (row.get("日付取得方式") or "").strip() != SnapshotAtSourceKind.FILENAME_YYYYMMDD:
        raise ValueError("日付取得方式はFILENAME_YYYYMMDDです")
    try:
        cutoff = datetime.strptime((row.get("締め時刻") or "").strip(), "%H:%M:%S").time()
    except ValueError as exc:
        raise ValueError("締め時刻はHH:MM:SSで指定してください") from exc
    return build_snapshot_time_policy(
        cutoff_time=cutoff,
        timezone_name=(row.get("timezone") or "").strip(),
        created_by=created_by,
        reason=reason,
        created_at=created_at,
    )
