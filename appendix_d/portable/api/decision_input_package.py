"""Immutable store and summary-specific validation for formal decision CSV inputs."""

from __future__ import annotations

import base64
import binascii
import json
import os
import uuid
from pathlib import Path

from .decision_input_contracts import DecisionInputError, parse_archive, template_zip
from .formal_shipment_daily import canonical_json, sha256


class PortableDecisionInputPackages:
    def __init__(self, paths) -> None:
        self.root = paths.formal_forecast / "DecisionInputs"
        self.sources = self.root / "Sources"
        self.root.mkdir(parents=True, exist_ok=True)
        self.sources.mkdir(parents=True, exist_ok=True)

    def template(self, summary: dict) -> bytes:
        return template_zip(
            [item["warehouse_id"] for item in summary["warehouses"]],
            [item["jan"] for item in summary["rows"]],
        )

    def create(self, build_id: str, summary: dict, payload: dict) -> dict:
        actor = str(payload.get("actor") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        if not actor or not reason or payload.get("confirm_decision_inputs") is not True:
            raise DecisionInputError("確認者、確認理由、正式入力の確認が必要です")
        try:
            archive = base64.b64decode(payload.get("archive_base64", ""), validate=True)
        except (binascii.Error, ValueError, TypeError) as exc:
            raise DecisionInputError("入力ZIPのBase64形式を確認してください") from exc
        parsed = parse_archive(archive)
        source_sha = sha256(archive)
        package_id = sha256(canonical_json({
            "format": "portable-decision-input-package-request-v1",
            "build_id": build_id,
            "daily_summary_sha256": summary["summary_sha256"],
            "source_archive_sha256": source_sha,
            "actor": actor,
            "reason": reason,
        }))
        target = self.root / f"{package_id}.json"
        if target.is_file():
            return self.get(package_id)
        issues = _summary_issues(summary, parsed["accepted"])
        accepted = parsed["accepted"]
        ready = all(accepted[name] for name in (
            "factory_supplies", "routes", "safety_stock_policies"
        ))
        result = {
            "format": "portable-decision-input-package-v1",
            "package_id": package_id,
            "build_id": build_id,
            "daily_summary_id": summary["summary_id"],
            "daily_summary_sha256": summary["summary_sha256"],
            "source_archive_sha256": source_sha,
            "actor": actor,
            "reason": reason,
            "status": (
                "BLOCKED" if not ready else
                "PARTIAL" if parsed["quarantines"] or issues else "READY"
            ),
            "ready_for_decision": ready,
            "sources": parsed["sources"],
            "accepted": accepted,
            "quarantines": parsed["quarantines"],
            "missing_or_outside_scope": issues,
        }
        result["package_sha256"] = sha256(canonical_json(result))
        _atomic(self.sources / f"{source_sha}.zip", archive)
        _atomic(target, canonical_json(result))
        return result

    def get(self, package_id: str) -> dict:
        if not _digest(package_id):
            raise DecisionInputError("Decision入力package IDを確認してください")
        target = self.root / f"{package_id}.json"
        if not target.is_file():
            raise DecisionInputError("Decision入力packageが見つかりません")
        try:
            result = json.loads(target.read_bytes())
            expected = result.pop("package_sha256")
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise DecisionInputError("Decision入力packageの整合性を確認できません") from exc
        actual = sha256(canonical_json(result))
        result["package_sha256"] = expected
        source_sha = result.get("source_archive_sha256")
        if not _digest(source_sha):
            raise DecisionInputError("Decision入力packageの整合性を確認できません")
        source = self.sources / f"{source_sha}.zip"
        if (
            actual != expected or result.get("package_id") != package_id
            or not source.is_file()
            or sha256(source.read_bytes()) != result["source_archive_sha256"]
        ):
            raise DecisionInputError("Decision入力packageの整合性を確認できません")
        return result


def _summary_issues(summary: dict, accepted: dict) -> list[dict]:
    warehouses = {item["warehouse_id"] for item in summary["warehouses"]}
    jans = {item["jan"] for item in summary["rows"]}
    issues = []
    route_warehouses = {item["warehouse_location_id"] for item in accepted["routes"]}
    safety_warehouses = {item["warehouse_id"] for item in accepted["safety_stock_policies"]}
    for warehouse in sorted(warehouses - route_warehouses):
        issues.append({"warehouse_id": warehouse, "code": "ROUTE_POLICY_MISSING"})
    for warehouse in sorted(warehouses - safety_warehouses):
        issues.append({"warehouse_id": warehouse, "code": "SAFETY_STOCK_POLICY_MISSING"})
    factories = {
        item["warehouse_location_id"]: item["factory_location_id"]
        for item in accepted["routes"] if item["warehouse_location_id"] in warehouses
    }
    supply_pairs = {
        (item["factory_id"], item["jan"]) for item in accepted["factory_supplies"]
    }
    for warehouse, factory in sorted(factories.items()):
        for jan in sorted(jans):
            if (factory, jan) not in supply_pairs:
                issues.append({
                    "factory_id": factory, "warehouse_id": warehouse, "jan": jan,
                    "code": "FACTORY_INVENTORY_MISSING",
                })
    for item in accepted["routes"]:
        if item["warehouse_location_id"] not in warehouses:
            issues.append({
                "warehouse_id": item["warehouse_location_id"],
                "code": "WAREHOUSE_OUTSIDE_DAILY_SUMMARY",
            })
    for item in accepted["safety_stock_policies"]:
        if item["warehouse_id"] not in warehouses:
            issues.append({
                "warehouse_id": item["warehouse_id"],
                "code": "SAFETY_POLICY_OUTSIDE_DAILY_SUMMARY",
            })
    for item in accepted["factory_supplies"]:
        if item["jan"] not in jans:
            issues.append({
                "factory_id": item["factory_id"], "jan": item["jan"],
                "code": "FACTORY_INVENTORY_OUTSIDE_DAILY_SUMMARY",
            })
    for item in accepted["production_plans"]:
        pair = (item["factory_id"], item["jan"])
        if item["jan"] not in jans:
            code = "PRODUCTION_PLAN_OUTSIDE_DAILY_SUMMARY"
        elif pair not in supply_pairs:
            code = "PRODUCTION_PLAN_FACTORY_INVENTORY_MISSING"
        else:
            continue
        issues.append({
            "factory_id": item["factory_id"], "jan": item["jan"], "code": code,
        })
    return issues


def _atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        if path.read_bytes() != content:
            raise DecisionInputError("同じIDの保存内容が一致しません")
        return
    temporary = path.with_name(f".{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _digest(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
