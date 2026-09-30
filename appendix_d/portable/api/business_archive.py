"""Read-only business ZIP preflight and a short local baseline backtest."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

import pandas as pd

from .forecast import forecast

MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 5_000
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
REQUIRED_SHIPMENT = {"出荷日", "JAN", "数量"}
REQUIRED_INVENTORY = {"商品コード", "明細バラ数", "賞味期限"}


class ArchiveError(ValueError):
    pass


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ArchiveError("CSVの文字コードを判定できません")


def _business_date(value: str) -> date | None:
    token = value.strip().split()[0]
    for pattern in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(token, pattern).date()
        except ValueError:
            pass
    return None


def _center_and_file_date(name: str) -> tuple[str, date | None]:
    base = PurePosixPath(name).name
    center = base.split("日時", 1)[0].strip() or "不明"
    match = re.search(r"_(\d{8})\.csv$", base, flags=re.IGNORECASE)
    return center, _business_date(match.group(1)) if match else None


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if not members or len(members) > MAX_MEMBERS:
        raise ArchiveError("ZIP内のファイル数が範囲外です")
    if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
        raise ArchiveError("ZIP展開後の容量が上限を超えます")
    seen: set[str] = set()
    for member in members:
        path = PurePosixPath(member.filename.replace("\\", "/"))
        key = path.as_posix().casefold()
        if path.is_absolute() or ".." in path.parts or key in seen or member.flag_bits & 1:
            raise ArchiveError("安全に展開できないZIPです")
        seen.add(key)
    return members


def _write_prepared(path: Path, daily: dict[tuple[str, str, date], Decimal]) -> None:
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("ds", "unique_id", "y"))
        for (center, jan, day), quantity in sorted(daily.items()):
            writer.writerow((day.isoformat(), f"{center}:{jan}", str(quantity)))
    temp.replace(path)


def analyze_archive(data: bytes, prepared_path: Path) -> dict:
    if not data or len(data) > MAX_ZIP_BYTES:
        raise ArchiveError("ZIPが空、または100 MBを超えています")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveError("ZIPを読み取れません") from exc

    shipment_rows = inventory_rows = auto_rows = review_rows = quarantine_rows = 0
    reason_counts: Counter[str] = Counter()
    shipment_jans: set[str] = set()
    inventory_codes: set[str] = set()
    inventory_valid_rows: Counter[str] = Counter()
    inventory_missing_expiry: Counter[str] = Counter()
    daily: dict[tuple[str, str, date], Decimal] = defaultdict(Decimal)
    shipment_dates: dict[str, set[date]] = defaultdict(set)
    shipment_files = inventory_files = ignored_files = 0

    with archive:
        for member in _safe_members(archive):
            if member.is_dir() or not member.filename.lower().endswith(".csv"):
                ignored_files += 1
                continue
            is_shipment = "出荷" in PurePosixPath(member.filename).name
            is_inventory = "在庫" in PurePosixPath(member.filename).name
            if not is_shipment and not is_inventory:
                ignored_files += 1
                continue
            center, file_date = _center_and_file_date(member.filename)
            with archive.open(member) as stream:
                reader = csv.DictReader(io.StringIO(_decode(stream.read()), newline=""))
            headers = set(reader.fieldnames or ())
            required = REQUIRED_SHIPMENT if is_shipment else REQUIRED_INVENTORY
            if not required.issubset(headers):
                quarantine_rows += 1
                reason_counts["HEADER_MISSING"] += 1
                continue
            if is_shipment:
                shipment_files += 1
                if file_date:
                    shipment_dates[center].add(file_date)
                for row in reader:
                    shipment_rows += 1
                    jan = str(row.get("JAN") or "").strip()
                    day = _business_date(str(row.get("出荷日") or ""))
                    try:
                        quantity = Decimal(str(row.get("数量") or "").replace(",", ""))
                    except InvalidOperation:
                        quantity = Decimal("NaN")
                    valid_quantity = quantity.is_finite() and quantity >= 0
                    if jan.isdigit() and len(jan) == 13 and day and valid_quantity:
                        shipment_jans.add(jan)
                        daily[(center, jan, day)] += quantity
                        auto_rows += 1
                    elif jan.isdigit() and len(jan) == 12 and day and valid_quantity:
                        review_rows += 1
                        reason_counts["JAN_12_DIGITS"] += 1
                    else:
                        quarantine_rows += 1
                        reason_counts["SHIPMENT_ROW_INVALID"] += 1
            else:
                inventory_files += 1
                for row in reader:
                    inventory_rows += 1
                    code = str(row.get("商品コード") or "").strip()
                    expiry = str(row.get("賞味期限") or "").strip()
                    try:
                        quantity = Decimal(str(row.get("明細バラ数") or "").replace(",", ""))
                    except InvalidOperation:
                        quantity = Decimal("NaN")
                    if (
                        code.isdigit()
                        and len(code) == 13
                        and quantity.is_finite()
                        and quantity >= 0
                    ):
                        inventory_codes.add(code)
                        inventory_valid_rows[code] += 1
                        if not expiry:
                            inventory_missing_expiry[code] += 1
                    else:
                        quarantine_rows += 1
                        reason_counts["INVENTORY_ROW_INVALID"] += 1

    if not shipment_files:
        raise ArchiveError("出荷CSVが見つかりません")
    matched = inventory_codes & shipment_jans
    for code, count in inventory_valid_rows.items():
        missing_expiry = inventory_missing_expiry[code]
        if code in matched:
            auto_rows += count - missing_expiry
            review_rows += missing_expiry
            reason_counts["EXPIRY_MISSING"] += missing_expiry
        else:
            review_rows += count
            reason_counts["INVENTORY_CODE_UNMATCHED"] += count
            reason_counts["EXPIRY_MISSING"] += missing_expiry
    prepared_path.parent.mkdir(parents=True, exist_ok=True)
    _write_prepared(prepared_path, daily)
    center_windows = []
    for center, days in sorted(shipment_dates.items()):
        latest = max(days)
        expected = {latest - timedelta(days=offset) for offset in range(35)}
        center_windows.append(
            {
                "center": center,
                "latest_date": latest.isoformat(),
                "backtest_ready": expected.issubset(days),
                "missing_recent_days": len(expected - days),
            }
        )
    status = "REVIEW_REQUIRED" if review_rows or quarantine_rows else "READY"
    return {
        "status": status,
        "files": {
            "shipment": shipment_files,
            "inventory": inventory_files,
            "ignored": ignored_files,
        },
        "rows": {
            "shipment": shipment_rows,
            "inventory": inventory_rows,
            "auto_confirmed": auto_rows,
            "review_required": review_rows,
            "quarantined": quarantine_rows,
        },
        "products": {
            "shipment_jans": len(shipment_jans),
            "inventory_codes": len(inventory_codes),
            "inventory_codes_matched_to_shipment_jan": len(matched),
            "inventory_codes_without_shipment": len(inventory_codes - shipment_jans),
        },
        "reasons": dict(sorted(reason_counts.items())),
        "center_windows": center_windows,
        "prepared_rows": len(daily),
        "notice": "過去データの参考評価です。正式な出荷指示には使用できません。",
    }


def run_reference_backtest(prepared_path: Path, work_dir: Path, analysis_id: str) -> dict:
    frame = pd.read_csv(prepared_path, dtype={"unique_id": "string"})
    frame["ds"] = pd.to_datetime(frame["ds"], format="%Y-%m-%d")
    frame["y"] = pd.to_numeric(frame["y"])
    results = []
    for center in sorted({value.split(":", 1)[0] for value in frame["unique_id"]}):
        center_frame = frame[frame["unique_id"].str.startswith(f"{center}:")].copy()
        latest = center_frame["ds"].max()
        start = latest - pd.Timedelta(days=34)
        window = center_frame[center_frame["ds"].between(start, latest)]
        active_ids = sorted(window["unique_id"].unique())
        grid = pd.MultiIndex.from_product(
            [active_ids, pd.date_range(start, latest, freq="D")], names=["unique_id", "ds"]
        )
        complete = (
            window.groupby(["unique_id", "ds"], as_index=True)["y"]
            .sum()
            .reindex(grid, fill_value=0)
            .reset_index()
        )
        origin = latest - pd.Timedelta(days=7)
        train = complete[complete["ds"] <= origin].copy()
        truth = complete[complete["ds"] > origin].copy()
        center_hash = hashlib.sha256(center.encode()).hexdigest()[:8]
        predictions = forecast(train, work_dir, f"{analysis_id}-{center_hash}")
        predicted = pd.DataFrame(predictions)
        predicted["target_date"] = pd.to_datetime(predicted["target_date"])
        joined = predicted.merge(
            truth, left_on=["unique_id", "target_date"], right_on=["unique_id", "ds"], how="inner"
        )
        absolute_error = (joined["yhat"] - joined["y"]).abs()
        denominator = float(joined["y"].sum())
        results.append(
            {
                "center": center,
                "train_start": train["ds"].min().date().isoformat(),
                "train_end": train["ds"].max().date().isoformat(),
                "test_start": truth["ds"].min().date().isoformat(),
                "test_end": truth["ds"].max().date().isoformat(),
                "series": len(active_ids),
                "points": len(joined),
                "mae": round(float(absolute_error.mean()), 4),
                "wape": (
                    round(float(absolute_error.sum()) / denominator, 6) if denominator else None
                ),
            }
        )
    return {
        "analysis_id": analysis_id,
        "provider": "builtin-baseline/seasonal_naive_7",
        "centers": results,
        "notice": "直近28日学習・続く7日評価の参考値です。正式比較・精度保証ではありません。",
    }


def content_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(body)
    temporary.replace(path)
    return hashlib.sha256(body).hexdigest()
