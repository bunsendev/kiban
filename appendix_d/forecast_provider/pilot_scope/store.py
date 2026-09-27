"""Pilot ScopeのSQLite / PostgreSQL不変台帳。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import PilotScopeKind
from .domain import (
    PilotScope,
    PilotScopedSnapshotReference,
    PilotScopeItem,
    PilotScopeReconciliation,
    PilotScopeVersion,
)
from .intake import PilotIntakeBinding, PilotIntakeSelector


class SqlitePilotScopeStore:
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

    def put(self, scope: PilotScope) -> PilotScope:
        value = scope.version
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            inserted = db.execute(
                "INSERT INTO pilot_scope_versions VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(pilot_scope_version) DO NOTHING",
                (
                    value.pilot_scope_version,
                    value.content_sha256,
                    value.scope_kind.value,
                    value.effective_from.isoformat(),
                    None if value.effective_to is None else value.effective_to.isoformat(),
                    value.approved_by,
                    value.reason,
                    value.created_at.isoformat(),
                ),
            )
            if inserted.rowcount == 1:
                db.executemany(
                    "INSERT INTO pilot_scope_items VALUES (?,?,?)",
                    [
                        (item.pilot_scope_version, item.jan, item.warehouse_id)
                        for item in scope.items
                    ],
                )
        current = self.get(scope.version.pilot_scope_version)
        if (
            current is None
            or current.version.content_sha256 != scope.version.content_sha256
            or current.items != scope.items
        ):
            raise ValueError("同じPilot Scope versionの内容は変更できません")
        return current

    def get(self, pilot_scope_version: str) -> PilotScope | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM pilot_scope_versions WHERE pilot_scope_version=?",
                (pilot_scope_version,),
            ).fetchone()
            if row is None:
                return None
            items = db.execute(
                "SELECT * FROM pilot_scope_items WHERE pilot_scope_version=? "
                "ORDER BY jan,warehouse_id",
                (pilot_scope_version,),
            ).fetchall()
        effective_to = row["effective_to"]
        version = PilotScopeVersion(
            row["pilot_scope_version"],
            row["content_sha256"],
            PilotScopeKind(row["scope_kind"]),
            date.fromisoformat(str(row["effective_from"])),
            None if effective_to is None else date.fromisoformat(str(effective_to)),
            row["approved_by"],
            row["reason"],
            datetime.fromisoformat(str(row["created_at"])),
        )
        return PilotScope(version, tuple(PilotScopeItem(**dict(item)) for item in items))

    def put_scoped_snapshot(
        self, value: PilotScopedSnapshotReference
    ) -> PilotScopedSnapshotReference:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            insert_scoped_snapshot_reference(db, value)
        current = self.get_scoped_snapshot(value.scoped_snapshot_id)
        if current != value:
            raise ValueError("同じscoped snapshot参照の内容は変更できません")
        return current

    def get_scoped_snapshot(self, scoped_snapshot_id: str) -> PilotScopedSnapshotReference | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM pilot_scoped_snapshot_references WHERE scoped_snapshot_id=?",
                (scoped_snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        reconciliation = PilotScopeReconciliation(
            row["source_sha256"],
            int(row["source_row_count"]),
            int(row["scoped_row_count"]),
            int(row["out_of_scope_row_count"]),
            int(row["quarantined_scope_row_count"]),
            Decimal(row["source_quantity_cases"]),
            Decimal(row["scoped_quantity_cases"]),
            Decimal(row["out_of_scope_quantity_cases"]),
            Decimal(row["quarantined_scope_quantity_cases"]),
        )
        return PilotScopedSnapshotReference(
            row["scoped_snapshot_id"],
            row["inventory_snapshot_id"],
            row["pilot_scope_version"],
            PilotScopeKind(row["scope_kind"]),
            reconciliation,
            datetime.fromisoformat(str(row["known_at"])),
            datetime.fromisoformat(str(row["recorded_at"])),
            row["content_sha256"],
        )

    def get_scoped_snapshot_id(
        self, inventory_snapshot_id: str, pilot_scope_version: str
    ) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT scoped_snapshot_id FROM pilot_scoped_snapshot_references "
                "WHERE inventory_snapshot_id=? AND pilot_scope_version=?",
                (inventory_snapshot_id, pilot_scope_version),
            ).fetchone()
        return None if row is None else row["scoped_snapshot_id"]

    def put_intake(self, value: PilotIntakeBinding) -> PilotIntakeBinding:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            inserted = db.execute(
                "INSERT INTO pilot_intake_versions VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(intake_version) DO NOTHING",
                (
                    value.intake_version,
                    value.content_sha256,
                    value.pilot_scope_version,
                    value.mapping_version,
                    value.created_by,
                    value.reason,
                    value.created_at.isoformat(),
                ),
            )
            if inserted.rowcount == 1:
                db.executemany(
                    "INSERT INTO pilot_intake_selectors VALUES (?,?,?,?,?)",
                    [
                        (
                            item.intake_version,
                            item.source_product_value,
                            item.source_location_code,
                            item.jan,
                            item.warehouse_id,
                        )
                        for item in value.selectors
                    ],
                )
        current = self.get_intake(value.intake_version)
        if (
            current is None
            or current.content_sha256 != value.content_sha256
            or current.selectors != value.selectors
        ):
            raise ValueError("同じPilot Intake versionの内容は変更できません")
        return current

    def get_intake(self, intake_version: str) -> PilotIntakeBinding | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM pilot_intake_versions WHERE intake_version=?",
                (intake_version,),
            ).fetchone()
            if row is None:
                return None
            selectors = db.execute(
                "SELECT * FROM pilot_intake_selectors WHERE intake_version=? "
                "ORDER BY source_product_value,source_location_code,jan,warehouse_id",
                (intake_version,),
            ).fetchall()
        return PilotIntakeBinding(
            row["intake_version"],
            row["content_sha256"],
            row["pilot_scope_version"],
            row["mapping_version"],
            row["created_by"],
            row["reason"],
            datetime.fromisoformat(str(row["created_at"])),
            tuple(PilotIntakeSelector(**dict(item)) for item in selectors),
        )

    def get_job_reconciliation(self, job_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM pilot_scope_job_reconciliations WHERE job_id=?", (job_id,)
            ).fetchone()
        return None if row is None else dict(row)


class PostgresPilotScopeStore(SqlitePilotScopeStore):
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


def insert_scoped_snapshot_reference(db, value: PilotScopedSnapshotReference) -> None:
    reconciliation = value.reconciliation
    db.execute(
        "INSERT INTO pilot_scoped_snapshot_references VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(scoped_snapshot_id) DO NOTHING",
        (
            value.scoped_snapshot_id,
            value.inventory_snapshot_id,
            value.pilot_scope_version,
            value.scope_kind.value,
            reconciliation.source_sha256,
            reconciliation.source_row_count,
            reconciliation.scoped_row_count,
            reconciliation.out_of_scope_row_count,
            reconciliation.quarantined_scope_row_count,
            str(reconciliation.source_quantity_cases),
            str(reconciliation.scoped_quantity_cases),
            str(reconciliation.out_of_scope_quantity_cases),
            str(reconciliation.quarantined_scope_quantity_cases),
            value.known_at.isoformat(),
            value.recorded_at.isoformat(),
            value.content_sha256,
        ),
    )
