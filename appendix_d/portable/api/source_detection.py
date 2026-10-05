"""Content-based CSV recognition shared by preflight and formal readers."""

import csv
import io
from pathlib import PurePosixPath


def read_source(archive, member):
    # Imported here to keep the existing archive public API compatible.
    from .business_archive import (
        REQUIRED_INVENTORY,
        REQUIRED_SHIPMENT,
        ArchiveError,
        _business_date,
        _center_and_file_date,
        _decode,
    )

    with archive.open(member) as stream:
        text = _decode(stream.read())
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = set(reader.fieldnames or ())
    shipment = REQUIRED_SHIPMENT <= headers
    inventory = REQUIRED_INVENTORY <= headers
    if shipment and inventory:
        raise ArchiveError(
            f"{member.filename}: 在庫と出荷の両方の列があります。種類を確認してください"
        )
    kind = "shipment" if shipment else "inventory" if inventory else None
    if kind is None:
        return None, None, None, reader

    rows = list(reader)
    centers = {
        str(row.get(column) or "").strip()
        for row in rows
        for column in ("倉庫", "倉庫名", "拠点")
        if str(row.get(column) or "").strip()
    }
    if len(centers) > 1:
        raise ArchiveError(f"{member.filename}: 複数の倉庫表記があります。拠点を確認してください")
    legacy_center, legacy_day = _center_and_file_date(member.filename)
    legacy = "日時" in PurePosixPath(member.filename).name
    center = next(iter(centers), legacy_center if legacy else None)
    if not center:
        raise ArchiveError(
            f"{member.filename}: 倉庫を特定できません。CSVの倉庫・倉庫名・拠点列を確認してください"
        )
    day_values = {
        str(row.get(column) or "").strip()
        for row in rows
        for column in ("基準日", "基準日時", "データ基準日")
        if str(row.get(column) or "").strip()
    }
    days = {_business_date(value) for value in day_values}
    if None in days or len(days) > 1:
        raise ArchiveError(f"{member.filename}: データ基準日を一つに特定できません")
    day = next(iter(days), legacy_day if legacy else None)
    if kind == "inventory" and day is None:
        raise ArchiveError(
            f"{member.filename}: 在庫の基準日がありません。基準日・基準日時列を確認してください"
        )
    # Shipment row dates do not prove a complete daily export; never invent zero days.
    return kind, center, day, csv.DictReader(io.StringIO(text, newline=""))
