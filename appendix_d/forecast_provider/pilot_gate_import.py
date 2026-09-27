"""Phase 3T Pilotの確認済みCSV登録とscope付き在庫ジョブ投入。"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

from .inventory_forecast_bridge import (
    PostgresInventoryForecastBridgeStore,
    SqliteInventoryForecastBridgeStore,
    parse_confirmed_inventory_forecast_bridge_csv,
)
from .inventory_foundation import (
    DirectoryInventorySourceReader,
    InventoryReferenceResolver,
    PostgresInventoryFoundationStore,
    SqliteInventoryFoundationStore,
    create_inventory_snapshot_job,
)
from .pilot_scope import (
    PostgresPilotScopeStore,
    SqlitePilotScopeStore,
    parse_confirmed_pilot_intake_csv,
    parse_confirmed_pilot_scope_csv,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="確認済みPilot契約の登録と在庫取込投入")
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    commands = parser.add_subparsers(dest="command", required=True)
    scope = commands.add_parser("scope")
    scope.add_argument("--csv", type=Path, required=True)
    scope.add_argument("--effective-from", type=date.fromisoformat, required=True)
    scope.add_argument("--effective-to", type=date.fromisoformat)
    scope.add_argument("--approved-by", required=True)
    scope.add_argument("--reason", required=True)
    bridge = commands.add_parser("bridge")
    bridge.add_argument("--csv", type=Path, required=True)
    bridge.add_argument("--created-by", required=True)
    bridge.add_argument("--reason", required=True)
    intake = commands.add_parser("intake")
    intake.add_argument("--csv", type=Path, required=True)
    intake.add_argument("--pilot-scope-version", required=True)
    intake.add_argument("--mapping-version", required=True)
    intake.add_argument("--created-by", required=True)
    intake.add_argument("--reason", required=True)
    enqueue = commands.add_parser("enqueue")
    enqueue.add_argument("--source-root", type=Path, required=True)
    enqueue.add_argument("--source-reference", required=True)
    enqueue.add_argument("--pilot-scope-version", required=True)
    enqueue.add_argument("--pilot-intake-version", required=True)
    enqueue.add_argument("--known-at", type=datetime.fromisoformat, required=True)
    enqueue.add_argument("--requested-by", required=True)
    return parser


def _stores(args):
    if args.sqlite is not None:
        return (
            SqliteInventoryFoundationStore(args.sqlite),
            SqlitePilotScopeStore(args.sqlite),
            SqliteInventoryForecastBridgeStore(args.sqlite),
        )
    return (
        PostgresInventoryFoundationStore(args.postgres_dsn),
        PostgresPilotScopeStore(args.postgres_dsn),
        PostgresInventoryForecastBridgeStore(args.postgres_dsn),
    )


def _required(value, label: str):
    if value is None:
        raise ValueError(f"{label}が登録されていません")
    return value


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    inventory, pilots, bridges = _stores(args)
    now = datetime.now(UTC)
    if args.command == "scope":
        scope = parse_confirmed_pilot_scope_csv(
            args.csv.read_bytes(),
            effective_from=args.effective_from,
            effective_to=args.effective_to,
            approved_by=args.approved_by,
            reason=args.reason,
            created_at=now,
        )
        stored = pilots.put(scope)
        result = {
            "pilot_scope_version": stored.version.pilot_scope_version,
            "scope_kind": stored.version.scope_kind.value,
            "target_count": len(stored.items),
        }
    elif args.command == "bridge":
        bridge = parse_confirmed_inventory_forecast_bridge_csv(
            args.csv.read_bytes(), created_by=args.created_by, reason=args.reason, created_at=now
        )
        stored = bridges.put(bridge)
        result = {"bridge_version": stored.version.bridge_version, "row_count": len(stored.records)}
    elif args.command == "intake":
        scope = _required(pilots.get(args.pilot_scope_version), "Pilot Scope")
        mapping = _required(inventory.get_mapping(args.mapping_version), "Inventory mapping")
        locations = inventory.list_locations(mapping.location_master_version)
        product_mappings = (
            inventory.list_product_mappings(mapping.product_mapping_version)
            if mapping.product_mapping_version is not None
            else ()
        )
        resolver = InventoryReferenceResolver(mapping, locations, product_mappings)
        binding = parse_confirmed_pilot_intake_csv(
            args.csv.read_bytes(),
            scope=scope,
            mapping=mapping,
            resolver=resolver,
            created_by=args.created_by,
            reason=args.reason,
            created_at=now,
        )
        stored = pilots.put_intake(binding)
        result = {
            "pilot_intake_version": stored.intake_version,
            "selector_count": len(stored.selectors),
        }
    else:
        scope = _required(pilots.get(args.pilot_scope_version), "Pilot Scope")
        binding = _required(pilots.get_intake(args.pilot_intake_version), "Pilot Intake")
        if binding.pilot_scope_version != scope.version.pilot_scope_version:
            raise ValueError("Pilot ScopeとPilot Intakeが一致しません")
        if args.known_at.tzinfo is None or args.known_at.utcoffset() is None:
            raise ValueError("known_atにはtimezoneを指定してください")
        known_at = args.known_at.astimezone(UTC)
        if known_at < scope.version.created_at or known_at < binding.created_at:
            raise ValueError("known_at時点に未登録のPilot契約は利用できません")
        content = DirectoryInventorySourceReader(args.source_root).read(args.source_reference)
        job = create_inventory_snapshot_job(
            source_reference=args.source_reference,
            source_sha256=hashlib.sha256(content).hexdigest(),
            mapping_version=binding.mapping_version,
            requested_by=args.requested_by,
            known_at=known_at,
            requested_at=now,
            pilot_scope_version=scope.version.pilot_scope_version,
            pilot_intake_version=binding.intake_version,
        )
        stored = inventory.put_job(job)
        result = {"job_id": stored.job_id, "status": stored.status.value}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
