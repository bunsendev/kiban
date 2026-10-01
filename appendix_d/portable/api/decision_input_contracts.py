"""Strict UTF-8 CSV contracts for formal shipment decision inputs."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime
from decimal import Decimal

from forecast_provider.inventory_foundation.contracts import RecommendationBasis
from forecast_provider.inventory_foundation.domain import canonical_decimal
from forecast_provider.shipment_decision import (
    FactorySupply,
    ProductionPlan,
    RouteLeadTimePolicy,
    SafetyStockPolicy,
)

from .formal_shipment_daily import canonical_json, sha256

MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 50_000
SCHEMAS = {
    "factory_inventory.csv": (
        "factory_snapshot_id", "snapshot_at", "factory_id", "jan", "inventory_cases",
    ),
    "production_plans.csv": (
        "plan_id", "plan_version", "factory_id", "jan", "completion_at",
        "quantity_cases",
    ),
    "routes.csv": (
        "policy_id", "policy_version", "location_master_version",
        "factory_location_id", "warehouse_location_id", "minimum_hours",
        "standard_hours", "maximum_hours", "recommendation_basis",
        "effective_from", "effective_to",
    ),
    "safety_stock.csv": (
        "policy_version", "warehouse_id", "coverage_days", "shipment_unit_cases",
    ),
}
REQUIRED_FILES = {"factory_inventory.csv", "routes.csv", "safety_stock.csv"}


class DecisionInputError(ValueError):
    pass


def parse_archive(raw: bytes) -> dict:
    if not raw or len(raw) > MAX_ARCHIVE_BYTES:
        raise DecisionInputError("入力ZIPは1 byte以上5 MiB以下にしてください")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError) as exc:
        raise DecisionInputError("Decision入力ZIPを読み取れません") from exc
    names = [item.filename for item in archive.infolist() if not item.is_dir()]
    if len(names) != len(set(names)) or any("/" in name or "\\" in name for name in names):
        raise DecisionInputError("ZIP直下に重複しないCSVを配置してください")
    unknown = sorted(set(names) - set(SCHEMAS))
    missing = sorted(REQUIRED_FILES - set(names))
    if unknown or missing:
        raise DecisionInputError(
            f"CSV構成を確認してください（不足:{','.join(missing) or 'なし'}、"
            f"対象外:{','.join(unknown) or 'なし'}）"
        )
    accepted = {
        "factory_supplies": [], "production_plans": [],
        "routes": [], "safety_stock_policies": [],
    }
    quarantines = []
    sources = []
    seen: dict[str, set[tuple]] = {name: set() for name in SCHEMAS}
    for name in sorted(names):
        info = archive.getinfo(name)
        if info.file_size > MAX_FILE_BYTES or info.compress_size > MAX_FILE_BYTES:
            raise DecisionInputError(f"{name}は2 MiB以下にしてください")
        content = archive.read(info)
        sources.append({"filename": name, "sha256": sha256(content), "bytes": len(content)})
        rows = _rows(name, content)
        if len(rows) > MAX_ROWS:
            raise DecisionInputError(f"{name}は{MAX_ROWS}行以下にしてください")
        target = _target(name)
        for row_number, row in enumerate(rows, start=2):
            row_hash = sha256(canonical_json(row))
            try:
                normalized, identity = _normalize(name, row)
                if identity in seen[name]:
                    raise ValueError("同じ識別子の行が重複しています")
                seen[name].add(identity)
                accepted[target].append(normalized)
            except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
                quarantines.append({
                    "filename": name,
                    "row_number": row_number,
                    "row_sha256": row_hash,
                    "reason_code": "ROW_CONTRACT_INVALID",
                    "message": str(exc),
                })
    return {"sources": sources, "accepted": accepted, "quarantines": quarantines}


def template_zip(warehouses: list[str], jans: list[str]) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        values = {
            "factory_inventory.csv": [
                {"factory_snapshot_id": "", "snapshot_at": "", "factory_id": "",
                 "jan": jan, "inventory_cases": ""}
                for jan in sorted(set(jans))
            ],
            "production_plans.csv": [],
            "routes.csv": [
                {"policy_id": "", "policy_version": "", "location_master_version": "",
                 "factory_location_id": "", "warehouse_location_id": warehouse,
                 "minimum_hours": "", "standard_hours": "", "maximum_hours": "",
                 "recommendation_basis": "", "effective_from": "", "effective_to": ""}
                for warehouse in sorted(set(warehouses))
            ],
            "safety_stock.csv": [
                {"policy_version": "", "warehouse_id": warehouse,
                 "coverage_days": "", "shipment_unit_cases": ""}
                for warehouse in sorted(set(warehouses))
            ],
        }
        for name, headers in SCHEMAS.items():
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\r\n")
            writer.writeheader()
            writer.writerows(values[name])
            archive.writestr(name, stream.getvalue().encode("utf-8-sig"))
    return target.getvalue()


def _rows(name: str, content: bytes) -> list[dict]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DecisionInputError(f"{name}はUTF-8 CSVで保存してください") from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if tuple(reader.fieldnames or ()) != SCHEMAS[name]:
            raise DecisionInputError(f"{name}の列名・列順が正式templateと一致しません")
        rows = list(reader)
    except csv.Error as exc:
        raise DecisionInputError(f"{name}のCSV形式を確認してください") from exc
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise DecisionInputError(f"{name}の列数を確認してください")
    return rows


def _target(name: str) -> str:
    return {
        "factory_inventory.csv": "factory_supplies",
        "production_plans.csv": "production_plans",
        "routes.csv": "routes",
        "safety_stock.csv": "safety_stock_policies",
    }[name]


def _normalize(name: str, row: dict) -> tuple[dict, tuple]:
    if name == "factory_inventory.csv":
        value = FactorySupply(
            row["factory_snapshot_id"], _datetime(row["snapshot_at"]),
            row["factory_id"], row["jan"], Decimal(row["inventory_cases"]),
        )
        return ({
            "snapshot_id": value.snapshot_id, "snapshot_at": value.snapshot_at.isoformat(),
            "factory_id": value.factory_id, "jan": value.jan,
            "inventory_cases": canonical_decimal(value.inventory_cases),
        }, (value.factory_id, value.jan))
    if name == "production_plans.csv":
        value = ProductionPlan(
            row["plan_id"], row["plan_version"], row["factory_id"], row["jan"],
            _datetime(row["completion_at"]), Decimal(row["quantity_cases"]),
        )
        return ({
            "plan_id": value.plan_id, "plan_version": value.plan_version,
            "factory_id": value.factory_id, "jan": value.jan,
            "completion_at": value.completion_at.isoformat(),
            "quantity_cases": canonical_decimal(value.quantity_cases),
        }, (value.plan_id,))
    if name == "routes.csv":
        value = RouteLeadTimePolicy(
            row["policy_id"], row["policy_version"], row["location_master_version"],
            row["factory_location_id"], row["warehouse_location_id"],
            int(row["minimum_hours"]), int(row["standard_hours"]),
            int(row["maximum_hours"]), RecommendationBasis(row["recommendation_basis"]),
            date.fromisoformat(row["effective_from"]),
            None if not row["effective_to"] else date.fromisoformat(row["effective_to"]),
        )
        return ({
            "policy_id": value.policy_id, "policy_version": value.policy_version,
            "location_master_version": value.location_master_version,
            "factory_location_id": value.factory_location_id,
            "warehouse_location_id": value.warehouse_location_id,
            "minimum_hours": value.minimum_hours, "standard_hours": value.standard_hours,
            "maximum_hours": value.maximum_hours,
            "recommendation_basis": value.recommendation_basis.value,
            "effective_from": value.effective_from.isoformat(),
            "effective_to": None if value.effective_to is None else value.effective_to.isoformat(),
        }, (value.warehouse_location_id,))
    value = SafetyStockPolicy(
        row["policy_version"], row["warehouse_id"], int(row["coverage_days"]),
        Decimal(row["shipment_unit_cases"]),
    )
    return ({
        "policy_version": value.policy_version, "warehouse_id": value.warehouse_id,
        "coverage_days": value.coverage_days,
        "shipment_unit_cases": canonical_decimal(value.shipment_unit_cases),
    }, (value.warehouse_id,))


def _datetime(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("日時はtimezone付きISO形式で指定してください")
    return result
