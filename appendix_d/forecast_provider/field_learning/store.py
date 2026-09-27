"""現場検証reference / decision / actualの追記型ストア。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from ..inventory_foundation.domain import canonical_decimal
from ..jobs.postgres_store import _Connection
from .contracts import FieldMode, OperatorDecision, OperatorReasonCode
from .domain import (
    FieldActualOutcomeEvent,
    FieldLearningConflict,
    FieldOperatorDecisionEvent,
    FieldReferenceCase,
)

if TYPE_CHECKING:
    from ..field_reference.domain import FieldReferencePolicy


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

    def put_reference_batch(
        self, policy: FieldReferencePolicy, cases: tuple[FieldReferenceCase, ...]
    ) -> tuple[FieldReferenceCase, ...]:
        """policyと全Pilot caseを単一transactionで追記する。"""

        if not cases or len({case.case_id for case in cases}) != len(cases):
            raise ValueError("参考caseが空または重複しています")
        if any(case.policy_version != policy.policy_version or case.mode is not FieldMode.SHADOW
               for case in cases):
            raise ValueError("参考caseのpolicy版またはmodeが一致しません")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO field_reference_policies VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(policy_version) DO NOTHING",
                (
                    policy.policy_version, policy.target_days,
                    canonical_decimal(policy.safety_stock_cases),
                    canonical_decimal(policy.shipment_multiple_cases),
                    policy.expiry_policy_version, policy.confirmed_by, policy.reason,
                    policy.confirmed_at.isoformat(), "WAREHOUSE_NOW_NO_INBOUND_SHADOW",
                ),
            )
            saved = db.execute(
                "SELECT * FROM field_reference_policies WHERE policy_version=?",
                (policy.policy_version,),
            ).fetchone()
            if (
                saved is None or int(saved["target_days"]) != policy.target_days
                or str(saved["safety_stock_cases"]) != canonical_decimal(policy.safety_stock_cases)
                or str(saved["shipment_multiple_cases"])
                != canonical_decimal(policy.shipment_multiple_cases)
                or saved["expiry_policy_version"] != policy.expiry_policy_version
                or saved["confirmed_by"] != policy.confirmed_by
                or saved["reason"] != policy.reason
                or datetime.fromisoformat(str(saved["confirmed_at"])) != policy.confirmed_at
                or saved["basis"] != "WAREHOUSE_NOW_NO_INBOUND_SHADOW"
            ):
                raise ValueError("同じ参考数量policy版の内容が一致しません")
            for case in cases:
                db.execute(
                    "INSERT INTO field_reference_cases VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(case_id) DO NOTHING",
                    (
                        case.case_id, case.business_date.isoformat(), case.jan,
                        case.canonical_product_id, case.warehouse_id,
                        case.forecast_center_id, case.forecast_run_id,
                        case.inventory_snapshot_id, case.pilot_scope_version,
                        case.identity_bridge_version,
                        canonical_decimal(case.system_forecast_quantity),
                        canonical_decimal(case.system_reference_quantity),
                        case.policy_version, case.mode.value, case.known_at.isoformat(),
                        case.recorded_at.isoformat(), case.content_sha256,
                    ),
                )
                row = db.execute(
                    "SELECT content_sha256 FROM field_reference_cases WHERE case_id=?",
                    (case.case_id,),
                ).fetchone()
                if row is None or row["content_sha256"] != case.content_sha256:
                    raise ValueError("同じ参考case IDの内容が一致しません")
        return tuple(self.get_reference_case(case.case_id) for case in cases)

    def get_reference_policy(self, policy_version: str) -> FieldReferencePolicy | None:
        from ..field_reference.domain import FieldReferencePolicy

        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM field_reference_policies WHERE policy_version=?",
                (policy_version,),
            ).fetchone()
        if row is None:
            return None
        return FieldReferencePolicy(
            row["policy_version"], int(row["target_days"]),
            Decimal(row["safety_stock_cases"]), Decimal(row["shipment_multiple_cases"]),
            row["expiry_policy_version"], row["confirmed_by"], row["reason"],
            datetime.fromisoformat(str(row["confirmed_at"])),
        )

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

    def append_actual_outcomes_batch(
        self, events: tuple[FieldActualOutcomeEvent, ...]
    ) -> tuple[FieldActualOutcomeEvent, ...]:
        """全caseのrevisionを同一transactionで検査し、全件または0件を追記する。"""

        if not events or len({item.case_id for item in events}) != len(events):
            raise ValueError("batchは空にできず、case_idは一意です")
        ordered = tuple(sorted(events, key=lambda item: item.case_id))
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for event in ordered:
                self._require_case(db, event.case_id)
                current = self._latest_revision(db, "field_actual_outcome_events", event.case_id)
                if event.revision != current + 1:
                    raise FieldLearningConflict("ほかの処理が先に実績を記録しました")
            for event in ordered:
                db.execute(
                    "INSERT INTO field_actual_outcome_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        event.actual_event_id, event.case_id, event.revision,
                        event.source_version, event.source_sha256,
                        *_optional_quantities(event), event.known_at.isoformat(),
                        event.recorded_at.isoformat(), event.content_sha256,
                    ),
                )
        return ordered

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
