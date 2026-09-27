"""現場検証reference / decision / actualの追記型ストア。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..inventory_foundation.domain import canonical_decimal
from ..jobs.postgres_store import _Connection
from .contracts import FieldMode, OperatorDecision, OperatorReasonCode
from .domain import (
    FieldActualOutcomeEvent,
    FieldLearningConflict,
    FieldOperatorDecisionEvent,
    FieldReferenceCase,
)


class SqliteFieldLearningStore:
    lock_clause = ""

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

    def put_reference_case(self, value: FieldReferenceCase) -> FieldReferenceCase:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO field_reference_cases VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(case_id) DO NOTHING",
                (
                    value.case_id,
                    value.business_date.isoformat(),
                    value.jan,
                    value.canonical_product_id,
                    value.warehouse_id,
                    value.forecast_center_id,
                    value.forecast_run_id,
                    value.inventory_snapshot_id,
                    value.pilot_scope_version,
                    value.identity_bridge_version,
                    canonical_decimal(value.system_forecast_quantity),
                    canonical_decimal(value.system_reference_quantity),
                    value.policy_version,
                    value.mode.value,
                    value.known_at.isoformat(),
                    value.recorded_at.isoformat(),
                    value.content_sha256,
                ),
            )
        current = self.get_reference_case(value.case_id)
        if current is None or current.content_sha256 != value.content_sha256:
            raise ValueError("同じreference caseの内容は変更できません")
        return current

    def get_reference_case(self, case_id: str) -> FieldReferenceCase | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM field_reference_cases WHERE case_id=?", (case_id,)
            ).fetchone()
        return None if row is None else _reference_case(row)

    def list_reference_cases(
        self, *, pilot_scope_version: str | None = None, limit: int = 500
    ) -> list[FieldReferenceCase]:
        if not 1 <= limit <= 500:
            raise ValueError("limitは1以上500以下です")
        where = " WHERE pilot_scope_version=?" if pilot_scope_version else ""
        params = (pilot_scope_version,) if pilot_scope_version else ()
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_reference_cases"
                f"{where} ORDER BY business_date DESC,case_id LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [_reference_case(row) for row in rows]

    def append_operator_decision(
        self, event: FieldOperatorDecisionEvent, expected_revision: int
    ) -> FieldOperatorDecisionEvent:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_case(db, event.case_id)
            current = self._latest_revision(db, "field_operator_decision_events", event.case_id)
            if current != expected_revision or event.revision != expected_revision + 1:
                raise FieldLearningConflict("ほかの利用者が先に担当者判断を記録しました")
            db.execute(
                "INSERT INTO field_operator_decision_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    event.decision_event_id,
                    event.case_id,
                    event.revision,
                    event.operator_decision.value,
                    None
                    if event.operator_quantity is None
                    else canonical_decimal(event.operator_quantity),
                    None
                    if event.operator_reason_code is None
                    else event.operator_reason_code.value,
                    event.operator_comment,
                    event.subject,
                    event.known_at.isoformat(),
                    event.recorded_at.isoformat(),
                ),
            )
        return event

    def list_operator_decisions(self, case_id: str) -> list[FieldOperatorDecisionEvent]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_operator_decision_events WHERE case_id=? ORDER BY revision",
                (case_id,),
            ).fetchall()
        return [_decision(row) for row in rows]

    def append_actual_outcome(
        self, event: FieldActualOutcomeEvent, expected_revision: int
    ) -> FieldActualOutcomeEvent:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_case(db, event.case_id)
            current = self._latest_revision(db, "field_actual_outcome_events", event.case_id)
            if current != expected_revision or event.revision != expected_revision + 1:
                raise FieldLearningConflict("ほかの処理が先に実績を記録しました")
            db.execute(
                "INSERT INTO field_actual_outcome_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event.actual_event_id,
                    event.case_id,
                    event.revision,
                    event.source_version,
                    event.source_sha256,
                    *_optional_quantities(event),
                    event.known_at.isoformat(),
                    event.recorded_at.isoformat(),
                    event.content_sha256,
                ),
            )
        return event

    def list_actual_outcomes(self, case_id: str) -> list[FieldActualOutcomeEvent]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM field_actual_outcome_events WHERE case_id=? ORDER BY revision",
                (case_id,),
            ).fetchall()
        return [_actual(row) for row in rows]

    def _require_case(self, db, case_id: str) -> None:
        row = db.execute(
            f"SELECT case_id FROM field_reference_cases WHERE case_id=?{self.lock_clause}",
            (case_id,),
        ).fetchone()
        if row is None:
            raise KeyError(case_id)

    def _latest_revision(self, db, table: str, case_id: str) -> int:
        row = db.execute(
            f"SELECT revision FROM {table} WHERE case_id=? "
            f"ORDER BY revision DESC LIMIT 1{self.lock_clause}",
            (case_id,),
        ).fetchone()
        return 0 if row is None else int(row["revision"])


class PostgresFieldLearningStore(SqliteFieldLearningStore):
    lock_clause = " FOR UPDATE"

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


def _reference_case(row) -> FieldReferenceCase:
    return FieldReferenceCase(
        row["case_id"],
        date.fromisoformat(str(row["business_date"])),
        row["jan"],
        row["canonical_product_id"],
        row["warehouse_id"],
        row["forecast_center_id"],
        row["forecast_run_id"],
        row["inventory_snapshot_id"],
        row["pilot_scope_version"],
        row["identity_bridge_version"],
        Decimal(row["system_forecast_quantity"]),
        Decimal(row["system_reference_quantity"]),
        row["policy_version"],
        FieldMode(row["mode"]),
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])),
        row["content_sha256"],
    )


def _decision(row) -> FieldOperatorDecisionEvent:
    quantity = row["operator_quantity"]
    reason = row["operator_reason_code"]
    return FieldOperatorDecisionEvent(
        row["decision_event_id"],
        row["case_id"],
        int(row["revision"]),
        OperatorDecision(row["operator_decision"]),
        None if quantity is None else Decimal(quantity),
        None if reason is None else OperatorReasonCode(reason),
        row["operator_comment"],
        row["subject"],
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])),
    )


def _actual(row) -> FieldActualOutcomeEvent:
    names = (
        "actual_shipped_quantity",
        "actual_demand_quantity",
        "stockout_quantity",
        "expired_quantity",
        "interwarehouse_transfer_quantity",
    )
    quantities = [None if row[name] is None else Decimal(row[name]) for name in names]
    return FieldActualOutcomeEvent(
        row["actual_event_id"],
        row["case_id"],
        int(row["revision"]),
        row["source_version"],
        row["source_sha256"],
        *quantities,
        datetime.fromisoformat(str(row["known_at"])),
        datetime.fromisoformat(str(row["recorded_at"])),
        row["content_sha256"],
    )


def _optional_quantities(value: FieldActualOutcomeEvent) -> tuple[str | None, ...]:
    return tuple(
        None if item is None else canonical_decimal(item)
        for item in (
            value.actual_shipped_quantity,
            value.actual_demand_quantity,
            value.stockout_quantity,
            value.expired_quantity,
            value.interwarehouse_transfer_quantity,
        )
    )
