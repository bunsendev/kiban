"""Freeze verified Portable shipment rows into a traceable daily build."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

import pandas as pd

from forecast_provider.daily import series_id

from .business_archive import _center_and_file_date, _safe_members

MIN_OBSERVED_DAYS = 28
RECENT_COMPLETE_DAYS = 7
MAX_HISTORY_DAYS = 365


class FormalShipmentBuildError(ValueError):
    pass


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_daily_shipment(
    *,
    archive_path: Path,
    prepared_path: Path,
    handoff: dict,
    registration_id: str,
    identities: list[dict],
    zero_when_file_present: bool,
    snapshot_dates_by_center: dict[str, date] | None = None,
    invalid_occurrences: set[tuple[str, str, date]] | None = None,
    invalid_file_dates: set[tuple[str, date]] | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build daily states without turning missing source files into zero."""

    archive_bytes = archive_path.read_bytes()
    if sha256(archive_bytes) != handoff["source_archive_sha256"]:
        raise FormalShipmentBuildError("原本ZIPの整合性を確認できません")
    if not prepared_path.is_file():
        raise FormalShipmentBuildError("確認済み出荷データが見つかりません")
    prepared_bytes = prepared_path.read_bytes()
    selected = {
        (item["source_center"], item["jan"]): item for item in identities
    }
    invalid_occurrences = invalid_occurrences or set()
    invalid_file_dates = invalid_file_dates or set()
    snapshot_dates_by_center = snapshot_dates_by_center or {}
    if not selected:
        raise FormalShipmentBuildError("予測対象の商品がありません")
    file_dates = _shipment_file_dates(archive_bytes, {key[0] for key in selected})
    missing_centers = sorted({key[0] for key in selected} - set(file_dates))
    if missing_centers:
        raise FormalShipmentBuildError("出荷CSVがない倉庫があります")
    center_windows = {
        center: {
            "train_start": max(min(days), max(days) - timedelta(days=364)),
            "train_end": max(days),
        }
        for center, days in file_dates.items()
    }
    overall_start = min(item["train_start"] for item in center_windows.values())
    overall_end = max(item["train_end"] for item in center_windows.values())
    quantities = _prepared_quantities(prepared_bytes, selected, overall_start, overall_end)
    rows: list[dict] = []
    summaries: list[dict] = []
    frame_rows: list[dict] = []
    for (center, jan), identity in sorted(selected.items()):
        start = center_windows[center]["train_start"]
        origin = center_windows[center]["train_end"]
        uid = series_id(identity["canonical_product_id"], identity["forecast_center_id"])
        observed = zero = missing = 0
        recent_missing = 0
        last_observed: str | None = None
        current = start
        while current <= origin:
            quantity = quantities.get((center, jan, current))
            issue = None
            if (center, current) in invalid_file_dates or (
                center, jan, current
            ) in invalid_occurrences:
                state = "PARTIAL_OR_INVALID"
                quantity = None
                missing += 1
                issue = "SOURCE_ROW_OR_FILE_INVALID"
                if current > origin - timedelta(days=RECENT_COMPLETE_DAYS):
                    recent_missing += 1
            elif quantity is not None:
                state = "OBSERVED"
                observed += 1
                last_observed = current.isoformat()
            elif current in file_dates[center] and zero_when_file_present:
                state = "CONFIRMED_ZERO"
                quantity = Decimal("0")
                zero += 1
                last_observed = current.isoformat()
            else:
                state = "MISSING"
                quantity = None
                missing += 1
                issue = (
                    "ZERO_POLICY_UNCONFIRMED"
                    if current in file_dates[center]
                    else "SOURCE_FILE_MISSING"
                )
                if current > origin - timedelta(days=RECENT_COMPLETE_DAYS):
                    recent_missing += 1
            row = {
                "canonical_product_id": identity["canonical_product_id"],
                "center_id": identity["forecast_center_id"],
                "jan": jan,
                "source_center": center,
                "ds": current.isoformat(),
                "unique_id": uid,
                "raw_quantity": None if quantity is None else str(quantity),
                "y": None if quantity is None else str(quantity),
                "state": state,
                "issue": issue,
            }
            rows.append(row)
            frame_rows.append(
                {"ds": pd.Timestamp(current), "unique_id": uid,
                 "source_center": center,
                 "y": None if quantity is None else float(quantity)}
            )
            current += timedelta(days=1)
        non_missing = observed + zero
        blockers = []
        if non_missing < MIN_OBSERVED_DAYS:
            blockers.append("HISTORY_LESS_THAN_28_DAYS")
        if recent_missing:
            blockers.append("RECENT_SOURCE_DAYS_MISSING")
        snapshot_date = snapshot_dates_by_center.get(center)
        if snapshot_date is not None and snapshot_date != origin:
            blockers.append("INVENTORY_SHIPMENT_AS_OF_MISMATCH")
        summaries.append(
            {
                "source_center": center,
                "jan": jan,
                "canonical_product_id": identity["canonical_product_id"],
                "forecast_center_id": identity["forecast_center_id"],
                "unique_id": uid,
                "observed_day_count": observed,
                "confirmed_zero_day_count": zero,
                "missing_day_count": missing,
                "last_observed_day": last_observed,
                "train_start": start.isoformat(),
                "train_end": origin.isoformat(),
                "inventory_snapshot_date": (
                    None if snapshot_date is None else snapshot_date.isoformat()
                ),
                "forecast_eligible": not blockers,
                "blocking_reasons": blockers,
            }
        )
    prepared_sha = sha256(prepared_bytes)
    identity_payload = {
        "format": "portable-formal-shipment-daily-v1",
        "registration_id": registration_id,
        "source_archive_sha256": handoff["source_archive_sha256"],
        "prepared_sha256": prepared_sha,
        "zero_when_file_present": zero_when_file_present,
        "invalid_occurrences": sorted(
            (center, jan, day.isoformat()) for center, jan, day in invalid_occurrences
        ),
        "invalid_file_dates": sorted(
            (center, day.isoformat()) for center, day in invalid_file_dates
        ),
        "train_start": overall_start.isoformat(),
        "train_end": overall_end.isoformat(),
        "center_windows": [
            {
                "source_center": center,
                "train_start": window["train_start"].isoformat(),
                "train_end": window["train_end"].isoformat(),
                "inventory_snapshot_date": (
                    snapshot_dates_by_center[center].isoformat()
                    if center in snapshot_dates_by_center else None
                ),
            }
            for center, window in sorted(center_windows.items())
        ],
        "series": summaries,
        "rows": rows,
    }
    build_id = "portable-daily-" + sha256(canonical_json(identity_payload))
    eligible = {item["unique_id"] for item in summaries if item["forecast_eligible"]}
    frame = pd.DataFrame(frame_rows)
    frame = frame[frame["unique_id"].isin(eligible)].reset_index(drop=True)
    build = {
        **identity_payload,
        "build_id": build_id,
        "status": "READY_FOR_FORECAST" if eligible else "BLOCKED",
        "eligible_series_count": len(eligible),
        "blocked_series_count": len(summaries) - len(eligible),
    }
    return build, frame


def daily_csv(build: dict) -> bytes:
    target = io.StringIO(newline="")
    fields = (
        "canonical_product_id", "center_id", "jan", "source_center", "ds",
        "unique_id", "raw_quantity", "y", "state", "issue",
    )
    writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(build["rows"])
    return target.getvalue().encode("utf-8-sig")


def _shipment_file_dates(raw: bytes, centers: set[str]) -> dict[str, set[date]]:
    output: dict[str, set[date]] = defaultdict(set)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for member in _safe_members(archive):
            name = PurePosixPath(member.filename).name
            if member.is_dir() or not name.lower().endswith(".csv") or "出荷" not in name:
                continue
            center, file_date = _center_and_file_date(member.filename)
            if center in centers and file_date is not None:
                output[center].add(file_date)
    return dict(output)


def _prepared_quantities(
    raw: bytes,
    selected: dict[tuple[str, str], dict],
    start: date,
    end: date,
) -> dict[tuple[str, str, date], Decimal]:
    output: dict[tuple[str, str, date], Decimal] = defaultdict(Decimal)
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        if tuple(reader.fieldnames or ()) != ("ds", "unique_id", "y"):
            raise FormalShipmentBuildError("確認済み出荷データの列が一致しません")
        for row in reader:
            unique_id = str(row["unique_id"])
            if ":" not in unique_id:
                continue
            center, jan = unique_id.rsplit(":", 1)
            if (center, jan) not in selected:
                continue
            day = date.fromisoformat(str(row["ds"]))
            if not start <= day <= end:
                continue
            quantity = Decimal(str(row["y"]))
            if not quantity.is_finite() or quantity < 0:
                raise FormalShipmentBuildError("出荷数量に不正な値があります")
            output[(center, jan, day)] += quantity
    except (UnicodeDecodeError, csv.Error, ValueError, InvalidOperation) as exc:
        if isinstance(exc, FormalShipmentBuildError):
            raise
        raise FormalShipmentBuildError("確認済み出荷データを読み込めません") from exc
    return dict(output)
