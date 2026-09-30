"""Build a traceable Portable package for the existing formal inventory intake."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

from forecast_provider.inventory_foundation import (
    InventoryInputMappingVersion,
    InventoryLocation,
    InventoryReferenceResolver,
    LocationType,
    NormalizedUnit,
    ProductIdentifierKind,
    parse_inventory_csv,
    validate_inventory_csv,
    validate_jan,
)

from .business_archive import _business_date, _center_and_file_date, _decode, _safe_members
from .business_review import latest_decisions

JST = ZoneInfo("Asia/Tokyo")
HANDOFF_FORMAT = "portable-formal-inventory-handoff-v1"
HEADERS = ("JAN", "拠点", "賞味期限", "明細バラ数", "基準日時")


class InventoryHandoffError(ValueError):
    pass


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_time(value: str) -> time:
    try:
        return time.fromisoformat(value.strip())
    except ValueError as exc:
        raise InventoryHandoffError("基準時刻はHH:MMで入力してください") from exc


def _parse_expiry(value: str) -> date | None:
    token = value.strip().split()[0] if value.strip() else ""
    return _business_date(token) if token else None


def _parse_quantity(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value.strip().replace(",", ""))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _location_id(center: str) -> str:
    return f"portable-warehouse-{hashlib.sha256(center.encode()).hexdigest()[:16]}"


def _config(payload: dict, centers: set[str]) -> tuple[dict[str, dict], dict]:
    actor = str(payload.get("actor") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if not actor or not reason:
        raise InventoryHandoffError("確認者と確認理由を入力してください")
    if not bool(payload.get("confirm_case")):
        raise InventoryHandoffError("明細バラ数を箱（CASE）として扱う確認が必要です")
    rows = payload.get("locations")
    if not isinstance(rows, list):
        raise InventoryHandoffError("拠点設定を確認してください")
    configs: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise InventoryHandoffError("拠点設定を確認してください")
        center = str(row.get("source_center") or "").strip()
        code = str(row.get("location_code") or "").strip()
        name = str(row.get("location_name") or "").strip()
        if center in configs or center not in centers or not code or not name:
            raise InventoryHandoffError("すべての拠点名と正式コードを確認してください")
        configs[center] = {
            "source_center": center,
            "location_id": _location_id(center),
            "location_code": code,
            "location_name": name,
            "snapshot_time": _parse_time(str(row.get("snapshot_time") or "")),
        }
    if set(configs) != centers:
        raise InventoryHandoffError("すべての最新在庫拠点を設定してください")
    return configs, {"actor": actor, "reason": reason, "confirm_case": True}


def _latest_inventory_members(archive: zipfile.ZipFile) -> dict[str, tuple[zipfile.ZipInfo, date]]:
    latest: dict[str, tuple[zipfile.ZipInfo, date]] = {}
    for member in _safe_members(archive):
        name = PurePosixPath(member.filename).name
        if member.is_dir() or not name.lower().endswith(".csv") or "在庫" not in name:
            continue
        center, file_date = _center_and_file_date(member.filename)
        if file_date is None:
            continue
        current = latest.get(center)
        if current is None or file_date > current[1]:
            latest[center] = (member, file_date)
    if not latest:
        raise InventoryHandoffError("日付を確認できる在庫CSVが見つかりません")
    return latest


def inventory_centers(archive_path: Path) -> list[dict]:
    with zipfile.ZipFile(archive_path) as archive:
        latest = _latest_inventory_members(archive)
    return [
        {"source_center": center, "latest_date": item[1].isoformat()}
        for center, item in sorted(latest.items())
    ]


def _mapped_jan(report: dict, decisions: dict[str, dict], code: str) -> str | None:
    try:
        return validate_jan(code)
    except ValueError:
        pass
    for issue in report.get("issues", []):
        if issue.get("category") != "inventory" or issue.get("source_value") != code:
            continue
        decision = decisions.get(issue["issue_id"])
        if decision and decision.get("action") == "MAP_JAN":
            try:
                return validate_jan(str(decision.get("corrected_jan") or ""))
            except ValueError:
                return None
    return None


def _csv_bytes(rows: dict[tuple[str, date], Decimal], location_code: str,
               snapshot_at: datetime) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(HEADERS)
    for (jan, expiry), quantity in sorted(rows.items()):
        writer.writerow(
            (jan, location_code, expiry.isoformat(), str(quantity), snapshot_at.isoformat())
        )
    return output.getvalue().encode("utf-8-sig")


def _mapping(mapping_version: str, location_version: str, actor: str,
             reason: str, created_at: datetime) -> InventoryInputMappingVersion:
    return InventoryInputMappingVersion(
        mapping_version, "JAN", ProductIdentifierKind.JAN, None, "拠点",
        location_version, "賞味期限", "明細バラ数", "基準日時",
        "明細バラ数", "箱", NormalizedUnit.CASE, "utf-8-sig", ",", 1,
        actor, reason, created_at,
    )


def build_inventory_handoff(
    archive_path: Path,
    report: dict,
    journal_path: Path,
    output_root: Path,
    payload: dict,
) -> dict:
    if _sha(archive_path.read_bytes()) != report["input_sha256"]:
        raise InventoryHandoffError("原本ZIPの整合性を確認できません")
    decisions = latest_decisions(journal_path)
    journal_sha = _sha(journal_path.read_bytes()) if journal_path.is_file() else _sha(b"")
    with zipfile.ZipFile(archive_path) as archive:
        latest = _latest_inventory_members(archive)
        configs, approval = _config(payload, set(latest))
        config_payload = {
            **approval,
            "locations": [
                {**value, "snapshot_time": value["snapshot_time"].isoformat(timespec="minutes")}
                for value in sorted(configs.values(), key=lambda item: item["source_center"])
            ],
        }
        handoff_id = _sha(_canonical_json({
            "format": HANDOFF_FORMAT,
            "analysis_id": report["analysis_id"],
            "decision_journal_sha256": journal_sha,
            "configuration": config_payload,
        }))
        package_dir = output_root / handoff_id
        manifest_path = package_dir / "manifest.json"
        if manifest_path.is_file():
            return json.loads(manifest_path.read_text(encoding="utf-8"))

        created_at = datetime.now(UTC)
        locations_payload = [
            {key: value for key, value in item.items() if key != "snapshot_time"}
            for item in sorted(configs.values(), key=lambda value: value["source_center"])
        ]
        location_version = "portable-locations-" + _sha(_canonical_json(locations_payload))[:24]
        mapping_version = "portable-inventory-map-" + _sha(_canonical_json({
            "location_master_version": location_version,
            "headers": HEADERS,
            "unit": "CASE",
        }))[:24]
        mapping = _mapping(mapping_version, location_version, approval["actor"],
                           approval["reason"], created_at)
        locations = tuple(
            InventoryLocation(
                location_version, item["location_id"], item["location_code"],
                item["location_name"], LocationType.WAREHOUSE, latest[center][1],
            )
            for center, item in sorted(configs.items())
        )
        resolver = InventoryReferenceResolver(mapping, locations)
        files = []
        blockers = []
        candidates: dict[str, bytes] = {}
        for center, (member, file_date) in sorted(latest.items()):
            config = configs[center]
            rows = csv.DictReader(io.StringIO(_decode(archive.read(member)), newline=""))
            totals: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
            source_rows = 0
            for row_number, row in enumerate(rows, start=2):
                source_rows += 1
                code = str(row.get("商品コード") or "").strip()
                jan = _mapped_jan(report, decisions, code)
                expiry = _parse_expiry(str(row.get("賞味期限") or ""))
                quantity = _parse_quantity(str(row.get("明細バラ数") or ""))
                reasons = []
                if jan is None:
                    reasons.append("JAN_UNRESOLVED")
                if expiry is None:
                    reasons.append("EXPIRY_UNRESOLVED")
                if quantity is None:
                    reasons.append("QUANTITY_INVALID")
                if reasons:
                    blockers.append({"source_center": center, "row_number": row_number,
                                     "reason_codes": reasons})
                    continue
                totals[(jan, expiry)] += quantity
            snapshot_at = datetime.combine(
                file_date, config["snapshot_time"], tzinfo=JST
            ).astimezone(UTC)
            content = _csv_bytes(totals, config["location_code"], snapshot_at)
            parsed = parse_inventory_csv(content, mapping)
            validation = validate_inventory_csv(parsed, mapping, resolver)
            if not validation.approval_ready:
                blockers.append({"source_center": center, "row_number": None,
                                 "reason_codes": ["FORMAL_VALIDATION_REJECTED"]})
            filename = f"{center}-{file_date.isoformat()}-formal-inventory.csv"
            candidates[filename] = content
            files.append({
                "source_center": center,
                "source_reference": member.filename,
                "source_sha256": _sha(archive.read(member)),
                "snapshot_at": snapshot_at.isoformat(),
                "candidate_file": filename,
                "candidate_sha256": _sha(content),
                "source_row_count": source_rows,
                "accepted_row_count": validation.reconciliation.accepted_row_count,
                "bucket_count": len(validation.buckets),
                "quantity_cases": str(validation.reconciliation.normalized_quantity_cases),
            })

    status = "READY_FOR_FORMAL_INTAKE" if not blockers else "BLOCKED"
    manifest = {
        "format": HANDOFF_FORMAT,
        "handoff_id": handoff_id,
        "status": status,
        "analysis_id": report["analysis_id"],
        "source_archive_sha256": report["input_sha256"],
        "decision_journal_sha256": journal_sha,
        "mapping_version": mapping_version,
        "location_master_version": location_version,
        "normalized_unit": "CASE",
        "source_quantity_column_name": "明細バラ数",
        "created_at": created_at.isoformat(),
        "approved_by": approval["actor"],
        "approval_reason": approval["reason"],
        "locations": locations_payload,
        "files": files,
        "blockers": blockers,
        "notice": (
            "正式inventory intakeへ渡せる検証済み候補です。Snapshotの最終承認は別Gateです。"
            if status == "READY_FOR_FORMAL_INTAKE"
            else "未解決行があるため正式inventory intakeへは渡しません。"
        ),
    }
    package_dir.mkdir(parents=True, exist_ok=False)
    for name, content in candidates.items():
        (package_dir / name).write_bytes(content)
    manifest_path.write_bytes(_canonical_json(manifest))
    if status == "READY_FOR_FORMAL_INTAKE":
        package_path = output_root / f"{handoff_id}.zip"
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr("manifest.json", _canonical_json(manifest))
            for name, content in sorted(candidates.items()):
                package.writestr(name, content)
    return manifest
