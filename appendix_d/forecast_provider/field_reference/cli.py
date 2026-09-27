"""Shadow参考補充量の検証とreference caseの明示登録。"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from ..expiry_simulation import ExpirySimulationService, build_expiry_policy
from ..field_learning import PostgresFieldLearningStore, SqliteFieldLearningStore
from ..inventory_forecast_bridge import (
    PostgresInventoryForecastBridgeStore,
    SqliteInventoryForecastBridgeStore,
)
from ..inventory_foundation import (
    PostgresInventoryFoundationStore,
    SqliteInventoryFoundationStore,
)
from ..jobs import PostgresRunStore, SqliteRunStore
from ..pilot_scope import PostgresPilotScopeStore, SqlitePilotScopeStore
from ..warehouse_projection import WarehouseProjectionService
from .domain import build_reference_policy
from .service import FieldReferenceBatchService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="承認済みPilotのShadow参考caseを検証・登録")
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    parser.add_argument("--pilot-scope-version", required=True)
    parser.add_argument("--identity-bridge-version", required=True)
    parser.add_argument("--forecast-run-id", required=True)
    parser.add_argument("--calculation-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--minimum-remaining-days", type=int, required=True)
    parser.add_argument("--attention-days", type=int, required=True)
    parser.add_argument("--expiry-policy-confirmed-by", required=True)
    parser.add_argument("--expiry-policy-reason", required=True)
    parser.add_argument("--expiry-policy-confirmed-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--target-days", type=int, required=True)
    parser.add_argument("--safety-stock-cases", required=True)
    parser.add_argument("--shipment-multiple-cases", required=True)
    parser.add_argument("--reference-policy-confirmed-by", required=True)
    parser.add_argument("--reference-policy-reason", required=True)
    parser.add_argument(
        "--reference-policy-confirmed-at", type=datetime.fromisoformat, required=True
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.sqlite is not None:
        inventory = SqliteInventoryFoundationStore(args.sqlite)
        pilot = SqlitePilotScopeStore(args.sqlite)
        bridge = SqliteInventoryForecastBridgeStore(args.sqlite)
        runs = SqliteRunStore(args.sqlite)
        fields = SqliteFieldLearningStore(args.sqlite)
    else:
        inventory = PostgresInventoryFoundationStore(args.postgres_dsn)
        pilot = PostgresPilotScopeStore(args.postgres_dsn)
        bridge = PostgresInventoryForecastBridgeStore(args.postgres_dsn)
        runs = PostgresRunStore(args.postgres_dsn)
        fields = PostgresFieldLearningStore(args.postgres_dsn)
    expiry = build_expiry_policy(
        minimum_remaining_days=args.minimum_remaining_days,
        attention_days=args.attention_days,
        confirmed_by=args.expiry_policy_confirmed_by,
        reason=args.expiry_policy_reason,
        confirmed_at=args.expiry_policy_confirmed_at,
    )
    reference = build_reference_policy(
        target_days=args.target_days,
        safety_stock_cases=args.safety_stock_cases,
        shipment_multiple_cases=args.shipment_multiple_cases,
        expiry_policy_version=expiry.policy_version,
        confirmed_by=args.reference_policy_confirmed_by,
        reason=args.reference_policy_reason,
        confirmed_at=args.reference_policy_confirmed_at,
    )
    service = FieldReferenceBatchService(
        ExpirySimulationService(WarehouseProjectionService(inventory, pilot, bridge, runs)),
        pilot, bridge, fields,
    )
    request = {
        "calculation_at": args.calculation_at,
        "pilot_scope_version": args.pilot_scope_version,
        "identity_bridge_version": args.identity_bridge_version,
        "forecast_run_id": args.forecast_run_id,
        "expiry_policy": expiry,
        "reference_policy": reference,
        "recorded_at": datetime.now(UTC),
    }
    cases = service.register(**request) if args.apply else service.prepare(**request)
    print(json.dumps({
        "mode": "SHADOW", "status": "APPLIED" if args.apply else "DRY_RUN",
        "notice": "倉庫単独の参考値。到着時点・工場供給を反映せず、出荷指示ではありません",
        "policy_version": reference.policy_version,
        "case_count": len(cases),
        "total_reference_cases": str(sum(
            (case.system_reference_quantity for case in cases), start=0
        )),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
