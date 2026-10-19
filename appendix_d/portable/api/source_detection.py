"""Content-based CSV recognition shared by preflight and formal readers."""

import csv
import io
import unicodedata
from pathlib import PurePosixPath


def _read_source(archive, member):
    # Imported here to keep the existing archive public API compatible.
    from .business_archive import (
        REQUIRED_SHIPMENT,
        ArchiveError,
        _business_date,
        _center_and_file_date,
        _decode,
    )

    with archive.open(member) as stream:
        text = _decode(stream.read())
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect, strict=True)
    raw_headers = reader.fieldnames or []
    clean_headers = [unicodedata.normalize("NFKC", h).strip().lstrip("\ufeff") for h in raw_headers]
    if len(clean_headers) != len(set(clean_headers)):
        raise ArchiveError(f"{member.filename}: 正規化後に同じ列名が重複しています")
    reader.fieldnames = clean_headers
    headers = set(reader.fieldnames or ())
    shipment = REQUIRED_SHIPMENT <= headers
    quantities = [h for h in ("明細バラ数", "現在在庫", "在庫数量", "在庫数", "現在庫", "数量")
                  if h in headers]
    inventory = bool({"JAN", "商品コード"} & headers) and "賞味期限" in headers and bool(quantities)
    if shipment and inventory:
        raise ArchiveError(
            f"{member.filename}: 在庫と出荷の両方の列があります。種類を確認してください"
        )
    kind = "shipment" if shipment else "inventory" if inventory else None
    if kind is None:
        return None, None, None, reader

    try:
        rows = list(reader)
    except csv.Error as exc:
        raise ArchiveError(f"{member.filename}: CSVの引用符・区切り・列構成が不正です") from exc
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ArchiveError(f"{member.filename}: 見出しと明細の列数が一致しません")
    if inventory and len(quantities) != 1:
        raise ArchiveError(f"{member.filename}: 在庫数量の列を一つに特定できません")
    for row in rows:
        if inventory:
            row["原本商品コード"] = row.get("商品コード", "")
            row["商品コード"] = row.get("JAN") or row.get("商品コード", "")
            row["原本数量列"] = quantities[0]
            row["明細バラ数"] = row.get(quantities[0], "")
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
    if legacy_day is not None and day is not None and legacy_day != day:
        raise ArchiveError(f"{member.filename}: 出荷日とファイル名・基準日が一致しません")
    if kind == "shipment" and day is not None and any(
        actual is not None and actual != day
        for row in rows
        for actual in [_business_date(str(row.get("出荷日") or ""))]
    ):
        raise ArchiveError(f"{member.filename}: 出荷日とファイルの基準日が一致しません")
    if kind == "inventory" and day is None:
        raise ArchiveError(
            f"{member.filename}: 在庫の基準日がありません。基準日・基準日時列を確認してください"
        )
    # Shipment row dates do not prove a complete daily export; never invent zero days.
    return kind, center, day, iter(rows)


def read_source(archive, member):
    from .business_archive import ArchiveError

    try:
        return _read_source(archive, member)
    except (csv.Error, ArchiveError) as exc:
        if str(exc).startswith(member.filename + ":"):
            raise
        raise ArchiveError(f"{member.filename}: {exc}") from exc
