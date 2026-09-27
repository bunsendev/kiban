"""業務確認済みPilot対象CSVだけを正式Scopeへ変換する。"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from .domain import PilotScope, build_pilot_scope

HEADER = ["JAN", "warehouse_id", "確認メモ"]
MAX_BYTES = 1024 * 1024


def parse_confirmed_pilot_scope_csv(
    content: bytes,
    *,
    effective_from: date,
    effective_to: date | None,
    approved_by: str,
    reason: str,
    created_at: datetime,
) -> PilotScope:
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Pilot Scope CSVは1 byte以上1 MiB以下です")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), strict=True)
        if reader.fieldnames != HEADER:
            raise ValueError("Pilot Scope CSVの列がtemplateと一致しません")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("Pilot Scope CSVはUTF-8形式で保存してください") from exc
    if not rows or len(rows) > 100:
        raise ValueError("Pilot Scope CSVの行数が不正です")
    if any(row.get("確認メモ") != "確認済み" or None in row for row in rows):
        raise ValueError("Pilot Scope CSVの全行を確認済みにしてください")
    return build_pilot_scope(
        pairs=[(row["JAN"], row["warehouse_id"]) for row in rows],
        effective_from=effective_from,
        effective_to=effective_to,
        approved_by=approved_by,
        reason=reason,
        created_at=created_at,
    )
