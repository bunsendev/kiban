"""Pilot期限別在庫のShadow FEFO計算CLI。"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

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
from .domain import build_expiry_policy
from .service import ExpirySimulationService


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"JSON化できない値: {type(value).__name__}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pilot倉庫の14日期限別FEFOをShadow計算")
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path)
    database.add_argument("--postgres-dsn")
    parser.add_argument("--pilot-scope-version", required=True)
    parser.add_argument("--identity-bridge-version", required=True)
    parser.add_argument("--forecast-run-id", required=True)
    parser.add_argument("--calculation-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--minimum-remaining-days", type=int, required=True)
    parser.add_argument("--attention-days", type=int, required=True)
    parser.add_argument("--policy-confirmed-by", required=True)
    parser.add_argument("--policy-reason", required=True)
    parser.add_argument("--policy-confirmed-at", type=datetime.fromisoformat, required=True)
    args = parser.parse_args(argv)
    if args.sqlite is not None:
        stores = (
            SqliteInventoryFoundationStore(args.sqlite),
            SqlitePilotScopeStore(args.sqlite),
            SqliteInventoryForecastBridgeStore(args.sqlite),
            SqliteRunStore(args.sqlite),
        )
    else:
        stores = (
            PostgresInventoryFoundationStore(args.postgres_dsn),
            PostgresPilotScopeStore(args.postgres_dsn),
            PostgresInventoryForecastBridgeStore(args.postgres_dsn),
            PostgresRunStore(args.postgres_dsn),
        )
    policy = build_expiry_policy(
        minimum_remaining_days=args.minimum_remaining_days,
        attention_days=args.attention_days,
        confirmed_by=args.policy_confirmed_by,
        reason=args.policy_reason,
        confirmed_at=args.policy_confirmed_at,
    )
    result = ExpirySimulationService(WarehouseProjectionService(*stores)).calculate(
        calculation_at=args.calculation_at.astimezone(UTC),
        pilot_scope_version=args.pilot_scope_version,
        identity_bridge_version=args.identity_bridge_version,
        forecast_run_id=args.forecast_run_id,
        policy=policy,
    )
    print(json.dumps(
        {"mode": "SHADOW", "meaning": "fefo_without_replenishment", **asdict(result)},
        ensure_ascii=False, sort_keys=True, default=_json_value,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
