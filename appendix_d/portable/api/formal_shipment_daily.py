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

from .business_archive import _safe_members
from .source_detection import read_source

MIN_OBSERVED_DAYS = 28
RECENT_COMPLETE_DAYS = 7
MAX_HISTORY_DAYS = 1096
HISTORY_POLICY_VERSION = "three-calendar-years-v1"


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
    quality_check: dict | None = None,
    forecast_mode: str = "A",
    execution_request_id: str | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build daily states without turning missing source files into zero."""

    archive_bytes = archive_path.read_bytes()
    if sha256(archive_bytes) != handoff["source_archive_sha256"]:
        raise FormalShipmentBuildError("原本ZIPの整合性を確認できません")
    if not prepared_path.is_file():
        raise FormalShipmentBuildError("確認済み出荷データが見つかりません")
    prepared_bytes = prepared_path.read_bytes()
    selected = {(item["source_center"], item["jan"]): item for item in identities}
    invalid_occurrences = invalid_occurrences or set()
    invalid_file_dates = invalid_file_dates or set()
    snapshot_dates_by_center = snapshot_dates_by_center or {}
    if not selected:
        raise FormalShipmentBuildError("予測対象の商品がありません")
    file_dates = _shipment_file_dates(archive_bytes, {key[0] for key in selected})
    window_dates = _shipment_file_dates(
        archive_bytes, {key[0] for key in selected}, include_observed=True
    )
    missing_centers = sorted({key[0] for key in selected} - set(window_dates))
    for center in missing_centers:
        # One missing warehouse must not stop other warehouses. Keep its days missing.
        anchor = snapshot_dates_by_center.get(center)
        if anchor is None:
            raise FormalShipmentBuildError("出荷CSVも在庫基準日もない倉庫があります")
        window_dates[center] = {anchor - timedelta(days=27), anchor}
    if forecast_mode == "C":
        for center, day in snapshot_dates_by_center.items():
            window_dates.setdefault(center, set()).add(day)
    center_windows = {
        center: {
            "train_start": max(
                min(days),
                (pd.Timestamp(max(days)) - pd.DateOffset(years=3) + pd.Timedelta(days=1)).date(),
            ),
            "train_end": max(days),
        }
        for center, days in window_dates.items()
    }
    overall_start = min(item["train_start"] for item in center_windows.values())
    overall_end = max(item["train_end"] for item in center_windows.values())
    quantities = _prepared_quantities(prepared_bytes, selected, overall_start, overall_end)
    quality_daily = {(r["warehouse"], r["jan"], r["date"]): r
                     for r in (quality_check or {}).get("daily", [])}
    quality_series = {(r["warehouse"], r["jan"]): r
                      for r in (quality_check or {}).get("series", [])}
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
        series_rows = []
        current = start
        while current <= origin:
            quantity = quantities.get((center, jan, current))
            issue = None
            if (center, current) in invalid_file_dates or (
                center,
                jan,
                current,
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
            elif current in file_dates.get(center, set()) and zero_when_file_present:
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
                    if current in file_dates.get(center, set())
                    else "SOURCE_FILE_MISSING"
                )
                if current > origin - timedelta(days=RECENT_COMPLETE_DAYS):
                    recent_missing += 1
            governed = quality_daily.get((center, jan, current.isoformat()))
            if governed and ((quality_check or {}).get("rules", {}).get("warehouses")
                             or forecast_mode == "C"):
                state = governed["state"]
                quantity = (Decimal(governed["quantity"])
                            if governed["quantity"] is not None else None)
                if state in {"CLOSED", "NOT_HANDLED"}:
                    quantity = None
                issue = ("QUALITY_POLICY_APPLIED"
                         if state not in {"OBSERVED", "CONFIRMED_ZERO"} else None)
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
            series_rows.append(row)
            frame_rows.append(
                {
                    "ds": pd.Timestamp(current),
                    "unique_id": uid,
                    "source_center": center,
                    "y": None if quantity is None else float(quantity),
                }
            )
            current += timedelta(days=1)
        required_start = origin - timedelta(days=MIN_OBSERVED_DAYS - 1)
        required_rows = [
            r
            for r in series_rows
            if r["unique_id"] == uid and required_start.isoformat() <= r["ds"] <= origin.isoformat()
        ]
        recognized_dates = {r["ds"] for r in required_rows if r["y"] is not None}
        recognized_count = len(recognized_dates)
        required_dates = [
            (required_start + timedelta(days=i)).isoformat() for i in range(MIN_OBSERVED_DAYS)
        ]
        missing_required = [day for day in required_dates if day not in recognized_dates]
        blockers = []
        if missing_required:
            blockers.append("HISTORY_LESS_THAN_28_DAYS")
        if recent_missing:
            blockers.append("RECENT_SOURCE_DAYS_MISSING")
        snapshot_date = snapshot_dates_by_center.get(center)
        if snapshot_date is not None and snapshot_date != origin:
            blockers.append("INVENTORY_SHIPMENT_AS_OF_MISMATCH")
        quality_item = quality_series.get((center, jan))
        if quality_check and quality_item is None:
            blockers.append("OUT_OF_SCOPE_QUALITY")
        if quality_item and quality_check.get("rules", {}).get("warehouses"):
            missing_required = quality_item["missing_dates"]
            recognized_count = quality_item["valid_records"]
        if quality_item and quality_check.get("rules", {}).get("warehouses"):
            if quality_item["normal_eligible"] and snapshot_date in {None, origin}:
                blockers = []
            elif not quality_item["normal_eligible"]:
                blockers = sorted({*blockers, "QUALITY_REVIEW_REQUIRED"})
        provisional = False
        if forecast_mode == "C":
            if (quality_item and quality_item["provisional_eligible"]
                    and snapshot_date in {None, origin}):
                provisional = bool(quality_item["missing_dates"])
                blockers = []
            else:
                blockers = sorted({*blockers, "MISSING_MODEL_INPUT_UNSUPPORTED"})
        summaries.append(
            {
                "source_center": center,
                "jan": jan,
                "canonical_product_id": identity["canonical_product_id"],
                "forecast_center_id": identity["forecast_center_id"],
                "unique_id": uid,
                "observed_day_count": sum(r["state"] == "OBSERVED" for r in series_rows),
                "confirmed_zero_day_count": sum(r["state"] == "CONFIRMED_ZERO"
                                                for r in series_rows),
                "missing_day_count": sum(r["state"] in {"MISSING", "PARTIAL_OR_INVALID"}
                                         for r in series_rows),
                "last_observed_day": last_observed,
                "train_start": start.isoformat(),
                "train_end": origin.isoformat(),
                "required_start": required_start.isoformat(),
                "required_end": origin.isoformat(),
                "required_day_count": quality_item["required_records"] if quality_item
                and quality_check.get("rules", {}).get("warehouses") else MIN_OBSERVED_DAYS,
                "recognized_required_days": recognized_count,
                "missing_required_dates": missing_required,
                "inventory_snapshot_date": (
                    None if snapshot_date is None else snapshot_date.isoformat()
                ),
                "forecast_eligible": not blockers,
                "blocking_reasons": blockers,
                **({"provisional": provisional} if forecast_mode == "C" else {}),
            }
        )
    prepared_sha = sha256(prepared_bytes)
    execution_end = overall_end
    execution_start = overall_start
    if quality_check:
        eligible_origins = [s["train_end"] for s in summaries if s["forecast_eligible"]]
        if eligible_origins:
            execution_end = date.fromisoformat(max(eligible_origins))
            # The existing production Run has one origin. Never silently advance an older
            # warehouse beyond the days checked for its normal/provisional forecast.
            for item in summaries:
                if item["forecast_eligible"] and item["train_end"] != execution_end.isoformat():
                    item["forecast_eligible"] = False
                    item["blocking_reasons"].append("FORECAST_ORIGIN_UNALIGNED")
            execution_start = min(date.fromisoformat(s["train_start"]) for s in summaries
                                  if s["forecast_eligible"])
    identity_payload = {
        "format": "portable-formal-shipment-daily-v1",
        "history_policy_version": HISTORY_POLICY_VERSION,
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
        "train_start": execution_start.isoformat(),
        "train_end": execution_end.isoformat(),
        "center_windows": [
            {
                "source_center": center,
                "train_start": window["train_start"].isoformat(),
                "train_end": window["train_end"].isoformat(),
                "inventory_snapshot_date": (
                    snapshot_dates_by_center[center].isoformat()
                    if center in snapshot_dates_by_center
                    else None
                ),
            }
            for center, window in sorted(center_windows.items())
        ],
        "series": summaries,
        "rows": rows,
    }
    if quality_check:
        identity_payload.update(quality_check_id=quality_check["id"], forecast_mode=forecast_mode)
    if execution_request_id:
        identity_payload["execution_request_id"] = execution_request_id
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
        "canonical_product_id",
        "center_id",
        "jan",
        "source_center",
        "ds",
        "unique_id",
        "raw_quantity",
        "y",
        "state",
        "issue",
    )
    writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(build["rows"])
    return target.getvalue().encode("utf-8-sig")


def _shipment_file_dates(
    raw: bytes, centers: set[str], *, include_observed=False
) -> dict[str, set[date]]:
    output: dict[str, set[date]] = defaultdict(set)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for member in _safe_members(archive):
            name = PurePosixPath(member.filename).name
            if member.is_dir() or not name.lower().endswith(".csv"):
                continue
            kind, center, file_date, reader = read_source(archive, member)
            if kind != "shipment":
                continue
            if center in centers and file_date is not None:
                output[center].add(file_date)
            if center in centers and include_observed:
                from .business_archive import _business_date

                for row in reader:
                    day = _business_date(str(row.get("出荷日") or ""))
                    if day is not None:
                        output[center].add(day)
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
