"""在庫・予測identity bridgeのSQLite / PostgreSQL不変台帳。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .domain import (
    InventoryForecastBridge,
    InventoryForecastBridgeRecord,
    InventoryForecastBridgeVersion,
)


class SqliteInventoryForecastBridgeStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text("utf-8"))

    def put(self, bridge: InventoryForecastBridge) -> InventoryForecastBridge:
        value = bridge.version
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            inserted = db.execute(
                "INSERT INTO inventory_forecast_bridge_versions VALUES (?,?,?,?,?) "
                "ON CONFLICT(bridge_version) DO NOTHING",
                (
                    value.bridge_version,
                    value.content_sha256,
                    value.created_by,
                    value.reason,
                    value.created_at.isoformat(),
                ),
            )
            if inserted.rowcount == 1:
                db.executemany(
                    "INSERT INTO inventory_forecast_bridge_records VALUES (?,?,?,?,?,?,?)",
                    [
                        (
                            item.bridge_version,
                            item.jan,
                            item.warehouse_id,
                            item.canonical_product_id,
                            item.forecast_center_id,
                            item.effective_from.isoformat(),
                            None if item.effective_to is None else item.effective_to.isoformat(),
                        )
                        for item in bridge.records
                    ],
                )
        current = self.get(bridge.version.bridge_version)
        if (
            current is None
            or current.version.content_sha256 != bridge.version.content_sha256
            or current.records != bridge.records
        ):
            raise ValueError("同じidentity bridge versionの内容は変更できません")
        return current

    def get(self, bridge_version: str) -> InventoryForecastBridge | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM inventory_forecast_bridge_versions WHERE bridge_version=?",
                (bridge_version,),
            ).fetchone()
            if row is None:
                return None
            records = db.execute(
                "SELECT * FROM inventory_forecast_bridge_records WHERE bridge_version=? "
                "ORDER BY jan,warehouse_id,effective_from,canonical_product_id,forecast_center_id",
                (bridge_version,),
            ).fetchall()
        version = InventoryForecastBridgeVersion(
            row["bridge_version"],
            row["content_sha256"],
            row["created_by"],
            row["reason"],
            datetime.fromisoformat(str(row["created_at"])),
        )
        return InventoryForecastBridge(
            version,
            tuple(
                InventoryForecastBridgeRecord(
                    value["bridge_version"],
                    value["jan"],
                    value["warehouse_id"],
                    value["canonical_product_id"],
                    value["forecast_center_id"],
                    date.fromisoformat(str(value["effective_from"])),
                    None
                    if value["effective_to"] is None
                    else date.fromisoformat(str(value["effective_to"])),
                )
                for value in records
            ),
        )


class PostgresInventoryForecastBridgeStore(SqliteInventoryForecastBridgeStore):
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.path = Path(".")
        self._initialize()

    def _raw_connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL利用にはpsycopgを追加してください") from exc
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _connect(self):
        return _Connection(self._raw_connect())

    def _initialize(self) -> None:
        with self._raw_connect() as db:
            for statement in Path(__file__).with_name("schema.sql").read_text("utf-8").split(";"):
                if statement.strip():
                    db.execute(statement)
