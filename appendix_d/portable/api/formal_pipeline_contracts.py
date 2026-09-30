"""Build approved Pilot contracts from a verified Portable inventory handoff."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date, datetime

from forecast_provider.field_pilot.inbox_classifier import header_sha256
from forecast_provider.field_pilot.inbox_policy import InboxPolicy, RequiredInput, SchemaRule
from forecast_provider.inventory_foundation import (
    InventoryInputMappingVersion,
    InventoryLocation,
    InventoryReferenceResolver,
    LocationMasterVersion,
    LocationType,
    NormalizedUnit,
    ProductIdentifierKind,
)
from forecast_provider.pilot_scope import build_pilot_scope
from forecast_provider.pilot_scope.intake import HEADER as PILOT_INTAKE_HEADER
from forecast_provider.pilot_scope.intake import parse_confirmed_pilot_intake_csv

from .inventory_handoff import HEADERS

MIN_PILOT_PRODUCTS = 10
MAX_PILOT_PRODUCTS = 20


class FormalPipelineError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedPipeline:
    policy: InboxPolicy
    files: dict[str, bytes]
    target_dates: dict[str, str]
    mapping: InventoryInputMappingVersion
    location_version: LocationMasterVersion
    locations: tuple[InventoryLocation, ...]
    scopes: tuple
    intakes: tuple


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def pipeline_identity(handoff: dict, payload: dict) -> tuple[str, dict]:
    actor = str(payload.get("actor") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if not actor or not reason or payload.get("confirm_pilot_scope") is not True:
        raise FormalPipelineError("試験対象、確認者、確認理由を確認してください")
    raw = payload.get("selections")
    if not isinstance(raw, list):
        raise FormalPipelineError("倉庫ごとの試験対象JANを確認してください")
    selections = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise FormalPipelineError("試験対象JANを確認してください")
        center = str(item.get("source_center") or "").strip()
        jans = sorted({str(value).strip() for value in item.get("jans", []) if str(value).strip()})
        if center in seen or not MIN_PILOT_PRODUCTS <= len(jans) <= MAX_PILOT_PRODUCTS:
            raise FormalPipelineError("各倉庫で10〜20商品のJANを選択してください")
        seen.add(center)
        selections.append({"source_center": center, "jans": jans})
    expected = {item["source_center"] for item in handoff["locations"]}
    if seen != expected:
        raise FormalPipelineError("すべての倉庫で試験対象を選択してください")
    approved = {"actor": actor, "reason": reason, "selections": sorted(
        selections, key=lambda item: item["source_center"]
    )}
    identity = sha256(canonical_json({
        "format": "portable-formal-pipeline-v1",
        "handoff_id": handoff["handoff_id"],
        **approved,
    }))
    return identity, approved


def eligible_products(handoff: dict, package_dir) -> list[dict]:
    output = []
    for item in handoff["files"]:
        rows = _read_rows(package_dir / item["candidate_file"], item["candidate_sha256"])
        output.append({
            "source_center": item["source_center"],
            "jans": sorted({row["JAN"] for row in rows}),
        })
    return output


def prepare_pipeline(handoff: dict, package_dir, approved: dict, *, created_at: datetime,
                     inventory_store, scope_store) -> PreparedPipeline:
    if handoff.get("status") != "READY_FOR_FORMAL_INTAKE":
        raise FormalPipelineError("正式取込候補が準備できていません")
    locations_by_center = {item["source_center"]: item for item in handoff["locations"]}
    selected_by_center = {item["source_center"]: set(item["jans"])
                          for item in approved["selections"]}
    source_rows = {}
    target_dates = {}
    effective_dates = []
    for item in handoff["files"]:
        rows = _read_rows(package_dir / item["candidate_file"], item["candidate_sha256"])
        available = {row["JAN"] for row in rows}
        selected = selected_by_center[item["source_center"]]
        if not selected.issubset(available):
            raise FormalPipelineError("候補に存在しないJANが選択されています")
        filtered = [row for row in rows if row["JAN"] in selected]
        if {row["JAN"] for row in filtered} != selected:
            raise FormalPipelineError("試験対象JANを候補から取得できません")
        source_rows[item["source_center"]] = filtered
        snapshot_dates = {datetime.fromisoformat(row["基準日時"]).date() for row in filtered}
        if len(snapshot_dates) != 1:
            raise FormalPipelineError("倉庫内の在庫基準日が一致しません")
        target = next(iter(snapshot_dates))
        target_dates[item["source_center"]] = target.isoformat()
        effective_dates.append(target)

    locations_payload = sorted(handoff["locations"], key=lambda item: item["source_center"])
    location_digest = sha256(canonical_json(locations_payload))
    location_version = LocationMasterVersion(
        handoff["location_master_version"], location_digest, approved["actor"],
        approved["reason"], created_at,
    )
    locations = tuple(
        InventoryLocation(
            handoff["location_master_version"], item["location_id"], item["location_code"],
            item["location_name"], LocationType.WAREHOUSE,
            date.fromisoformat(target_dates[item["source_center"]]),
        )
        for item in locations_payload
    )
    inventory_store.put_location_master(location_version, locations)
    mapping = InventoryInputMappingVersion(
        handoff["mapping_version"], "JAN", ProductIdentifierKind.JAN, None, "拠点",
        handoff["location_master_version"], "賞味期限", "明細バラ数", "基準日時",
        handoff["source_quantity_column_name"], "箱", NormalizedUnit.CASE,
        "utf-8-sig", ",", 1, approved["actor"], approved["reason"], created_at,
    )
    inventory_store.put_mapping(mapping)
    resolver = InventoryReferenceResolver(mapping, locations)
    scopes = []
    intakes = []
    rules = []
    required = []
    files = {}
    for center, rows in sorted(source_rows.items()):
        location = locations_by_center[center]
        selected = selected_by_center[center]
        scope = build_pilot_scope(
            pairs=[(jan, location["location_id"]) for jan in sorted(selected)],
            effective_from=date.fromisoformat(target_dates[center]), effective_to=None,
            approved_by=approved["actor"], reason=approved["reason"], created_at=created_at,
        )
        scope_store.put(scope)
        intake_csv = _intake_csv(selected, location)
        intake = parse_confirmed_pilot_intake_csv(
            intake_csv, scope=scope, mapping=mapping, resolver=resolver,
            created_by=approved["actor"], reason=approved["reason"], created_at=created_at,
        )
        scope_store.put_intake(intake)
        content = _candidate_csv(rows)
        filename = f"{center}-{target_dates[center]}-pilot-inventory.csv"
        files[filename] = content
        schema_id = f"portable-pilot-{sha256(content)[:24]}"
        required.append(RequiredInput("WAREHOUSE_INVENTORY", location["location_code"],
                                      location["location_name"]))
        rules.append(SchemaRule(
            schema_id, "WAREHOUSE_INVENTORY", location["location_code"],
            header_sha256(HEADERS), HEADERS, "基準日時", "%Y-%m-%dT%H:%M:%S%z",
            "明細バラ数", "拠点", mapping.mapping_version,
            scope.version.pilot_scope_version, intake.intake_version,
            "JAN", "賞味期限", "箱", "CASE",
        ))
        scopes.append(scope)
        intakes.append(intake)
    policy_payload = {
        "handoff": handoff["handoff_id"],
        "scopes": [value.version.pilot_scope_version for value in scopes],
    }
    policy_version = f"portable-pipeline-{sha256(canonical_json(policy_payload))}"
    return PreparedPipeline(
        InboxPolicy(policy_version, tuple(required), tuple(rules)), files, target_dates,
        mapping, location_version, locations, tuple(scopes), tuple(intakes),
    )


def _read_rows(path, expected_sha: str) -> list[dict]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise FormalPipelineError("正式取込候補を読み込めません") from exc
    if sha256(content) != expected_sha:
        raise FormalPipelineError("正式取込候補の整合性を確認できません")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), strict=True)
        if tuple(reader.fieldnames or ()) != HEADERS:
            raise FormalPipelineError("正式取込候補の列が一致しません")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise FormalPipelineError("正式取込候補CSVを読み込めません") from exc
    return rows


def _candidate_csv(rows: list[dict]) -> bytes:
    target = io.StringIO(newline="")
    writer = csv.DictWriter(target, fieldnames=HEADERS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return target.getvalue().encode("utf-8-sig")


def _intake_csv(jans: set[str], location: dict) -> bytes:
    target = io.StringIO(newline="")
    writer = csv.writer(target, lineterminator="\n")
    writer.writerow(PILOT_INTAKE_HEADER)
    for jan in sorted(jans):
        writer.writerow((jan, location["location_code"], jan, location["location_id"], "確認済み"))
    return target.getvalue().encode("utf-8-sig")
