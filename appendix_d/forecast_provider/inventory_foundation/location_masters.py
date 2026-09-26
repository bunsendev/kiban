"""確認済みlocation master CSVの決定的な正式取込。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date, datetime

from .contracts import LocationType
from .locations import InventoryLocation, LocationMasterVersion

LOCATION_MASTER_HEADER = [
    "拠点コード",
    "拠点名",
    "拠点種別",
    "適用開始日",
    "適用終了日",
    "確認メモ",
]
CONFIRMED_NOTE = "確認済み"
MAX_LOCATION_MASTER_BYTES = 1024 * 1024
MAX_LOCATION_MASTER_ROWS = 10_000


@dataclass(frozen=True)
class LocationMasterImport:
    version: LocationMasterVersion
    locations: tuple[InventoryLocation, ...]


def parse_confirmed_location_master_csv(
    content: bytes,
    *,
    created_by: str,
    reason: str,
    created_at: datetime,
) -> LocationMasterImport:
    """全行が人手確認済みのCSVだけを正式location masterへ変換する。"""

    if not content or len(content) > MAX_LOCATION_MASTER_BYTES:
        raise ValueError("location masterは1 byte以上1 MiB以下にしてください")
    try:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames != LOCATION_MASTER_HEADER:
            raise ValueError("location masterの列がtemplateと一致しません")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("location masterはUTF-8 CSVで保存してください") from exc
    if not rows or len(rows) > MAX_LOCATION_MASTER_ROWS:
        raise ValueError("location masterの行数が不正です")

    values: list[dict] = []
    seen_codes: set[str] = set()
    for row in rows:
        code = (row.get("拠点コード") or "").strip()
        name = (row.get("拠点名") or "").strip()
        type_value = (row.get("拠点種別") or "").strip()
        effective_from = _date(row.get("適用開始日"), required=True)
        effective_to = _date(row.get("適用終了日"), required=False)
        note = (row.get("確認メモ") or "").strip()
        if not code or not name:
            raise ValueError("拠点コードと拠点名は全行で必須です")
        if note != CONFIRMED_NOTE:
            raise ValueError("全行の確認メモを確認済みにしてください")
        if code in seen_codes:
            raise ValueError("拠点コードが重複しています")
        seen_codes.add(code)
        try:
            location_type = LocationType(type_value)
        except ValueError as exc:
            raise ValueError("拠点種別はFACTORYまたはWAREHOUSEです") from exc
        assert effective_from is not None
        if effective_to is not None and effective_to < effective_from:
            raise ValueError("適用終了日は適用開始日以降にしてください")
        values.append(
            {
                "effective_from": effective_from.isoformat(),
                "effective_to": None if effective_to is None else effective_to.isoformat(),
                "location_code": code,
                "location_id": _location_id(code),
                "location_name": name,
                "location_type": location_type.value,
            }
        )

    payload = sorted(values, key=lambda item: item["location_code"])
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    digest = hashlib.sha256(encoded).hexdigest()
    version_id = f"inventory-location-map-{digest}"
    version = LocationMasterVersion(version_id, digest, created_by, reason, created_at)
    locations = tuple(
        InventoryLocation(
            version_id,
            item["location_id"],
            item["location_code"],
            item["location_name"],
            LocationType(item["location_type"]),
            date.fromisoformat(item["effective_from"]),
            None
            if item["effective_to"] is None
            else date.fromisoformat(item["effective_to"]),
        )
        for item in payload
    )
    return LocationMasterImport(version, locations)


def _location_id(location_code: str) -> str:
    digest = hashlib.sha256(location_code.encode("utf-8")).hexdigest()
    return f"location-{digest[:24]}"


def _date(value: str | None, *, required: bool) -> date | None:
    normalized = (value or "").strip()
    if not normalized:
        if required:
            raise ValueError("適用開始日は全行で必須です")
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("適用日はYYYY-MM-DDで指定してください") from exc
