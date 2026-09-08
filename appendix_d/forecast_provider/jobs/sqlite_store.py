"""SQLiteによる参照用run台帳。各起点の結果を一transactionで確定する。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..errors import ContractViolationError
from .contracts import (
    Expectation,
    ForecastValue,
    OriginDefinition,
    OriginLease,
    OriginOutput,
    RunDefinition,
    RunStatus,
)


class StaleLeaseError(RuntimeError):
    """別attemptの結果を確定しようとした。"""


class SqliteRunStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS forecast_runs (
                  run_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
                  condition_fingerprint TEXT NOT NULL, provider_id TEXT NOT NULL,
                  model_name TEXT NOT NULL, seed INTEGER NOT NULL,
                  status TEXT NOT NULL, cancellation_requested INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS forecast_origins (
                  run_id TEXT NOT NULL REFERENCES forecast_runs(run_id), origin_date TEXT NOT NULL,
                  cutoff_at TEXT NOT NULL, status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
                  model_artifact TEXT, context_artifact TEXT, error TEXT,
                  PRIMARY KEY(run_id, origin_date)
                );
                CREATE TABLE IF NOT EXISTS forecast_expectations (
                  run_id TEXT NOT NULL, unique_id TEXT NOT NULL, origin_date TEXT NOT NULL,
                  target_date TEXT NOT NULL, horizon INTEGER NOT NULL, status TEXT NOT NULL,
                  PRIMARY KEY(run_id, unique_id, origin_date, target_date),
                  FOREIGN KEY(run_id, origin_date) REFERENCES forecast_origins(run_id, origin_date)
                );
                CREATE TABLE IF NOT EXISTS forecast_values (
                  run_id TEXT NOT NULL, unique_id TEXT NOT NULL, origin_date TEXT NOT NULL,
                  target_date TEXT NOT NULL, horizon INTEGER NOT NULL, forecast_kind TEXT NOT NULL,
                  quantile TEXT NOT NULL DEFAULT '', yhat_raw TEXT NOT NULL, yhat TEXT NOT NULL,
                  attempt INTEGER NOT NULL,
                  PRIMARY KEY(run_id, unique_id, origin_date, target_date, forecast_kind, quantile),
                  FOREIGN KEY(run_id, origin_date) REFERENCES forecast_origins(run_id, origin_date)
                );
                CREATE TABLE IF NOT EXISTS forecast_failures (
                  run_id TEXT NOT NULL, origin_date TEXT NOT NULL, attempt INTEGER NOT NULL,
                  error TEXT NOT NULL, retryable INTEGER NOT NULL,
                  PRIMARY KEY(run_id, origin_date, attempt)
                );
                """
            )

    def create_run(
        self,
        definition: RunDefinition,
        origins: tuple[OriginDefinition, ...],
        expectations: tuple[Expectation, ...],
    ) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO forecast_runs VALUES (?,?,?,?,?,?,?,0)",
                (
                    definition.run_id,
                    definition.experiment_id,
                    definition.condition_fingerprint,
                    definition.provider_id,
                    definition.model_name,
                    definition.seed,
                    "QUEUED",
                ),
            )
            db.executemany(
                "INSERT INTO forecast_origins(run_id,origin_date,cutoff_at,status) "
                "VALUES (?,?,?,?)",
                [
                    (
                        definition.run_id,
                        o.origin_date.isoformat(),
                        o.cutoff_at.isoformat(),
                        "QUEUED",
                    )
                    for o in origins
                ],
            )
            db.executemany(
                "INSERT INTO forecast_expectations VALUES (?,?,?,?,?,?)",
                [
                    (
                        definition.run_id,
                        e.unique_id,
                        e.origin_date.isoformat(),
                        e.target_date.isoformat(),
                        e.horizon,
                        "PLANNED",
                    )
                    for e in expectations
                ],
            )

    def start_or_resume(self, run_id: str, condition_fingerprint: str) -> None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM forecast_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row["condition_fingerprint"] != condition_fingerprint:
                raise ContractViolationError("run条件が存在しないか一致しません")
            if row["status"] in ("SUCCEEDED", "CANCELLED"):
                raise ContractViolationError("完了済みrunは再開できません")
            db.execute(
                "UPDATE forecast_origins SET status='QUEUED' WHERE run_id=? AND status='RUNNING'",
                (run_id,),
            )
            db.execute("UPDATE forecast_runs SET status='RUNNING' WHERE run_id=?", (run_id,))

    def claim_next_origin(self, run_id: str) -> OriginLease | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM forecast_origins WHERE run_id=? AND status='QUEUED' "
                "ORDER BY origin_date LIMIT 1",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            attempt = row["attempt"] + 1
            db.execute(
                "UPDATE forecast_origins SET status='RUNNING',attempt=?,error=NULL "
                "WHERE run_id=? AND origin_date=?",
                (attempt, run_id, row["origin_date"]),
            )
            origin = OriginDefinition(
                date.fromisoformat(row["origin_date"]), datetime.fromisoformat(row["cutoff_at"])
            )
            return OriginLease(run_id, origin, attempt)

    @staticmethod
    def _validate_value(lease: OriginLease, value: ForecastValue) -> None:
        if value.origin_date != lease.origin.origin_date:
            raise ContractViolationError("予測値のorigin不一致")
        if (
            value.target_date <= value.origin_date
            or value.horizon != (value.target_date - value.origin_date).days
        ):
            raise ContractViolationError("予測値のtarget/horizon不一致")
        if value.yhat != max(value.yhat_raw, Decimal(0)):
            raise ContractViolationError("yhat=max(yhat_raw,0)ではありません")
        if value.forecast_kind == "POINT" and value.quantile is not None:
            raise ContractViolationError("POINTのquantileはNoneです")
        if value.forecast_kind == "QUANTILE" and not (
            value.quantile is not None and Decimal(0) < value.quantile < Decimal(1)
        ):
            raise ContractViolationError("QUANTILE値が不正です")

    def complete_origin(self, lease: OriginLease, output: OriginOutput) -> None:
        for value in output.values:
            self._validate_value(lease, value)
        points = {
            (v.unique_id, v.target_date.isoformat())
            for v in output.values
            if v.forecast_kind == "POINT"
        }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,attempt FROM forecast_origins WHERE run_id=? AND origin_date=?",
                (lease.run_id, lease.origin.origin_date.isoformat()),
            ).fetchone()
            if row is None or row["status"] != "RUNNING" or row["attempt"] != lease.attempt:
                raise StaleLeaseError("起点leaseは失効しています")
            expected = {
                (r["unique_id"], r["target_date"])
                for r in db.execute(
                    "SELECT unique_id,target_date FROM forecast_expectations "
                    "WHERE run_id=? AND origin_date=?",
                    (lease.run_id, lease.origin.origin_date.isoformat()),
                )
            }
            if points != expected:
                raise ContractViolationError("必要POINTが過不足なく揃っていません")
            db.executemany(
                "INSERT INTO forecast_values VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        lease.run_id,
                        v.unique_id,
                        v.origin_date.isoformat(),
                        v.target_date.isoformat(),
                        v.horizon,
                        v.forecast_kind,
                        "" if v.quantile is None else str(v.quantile),
                        str(v.yhat_raw),
                        str(v.yhat),
                        lease.attempt,
                    )
                    for v in output.values
                ],
            )
            db.execute(
                "UPDATE forecast_expectations SET status='SUCCESS' "
                "WHERE run_id=? AND origin_date=?",
                (lease.run_id, lease.origin.origin_date.isoformat()),
            )
            db.execute(
                "UPDATE forecast_origins SET status='SUCCEEDED',model_artifact=?,"
                "context_artifact=? WHERE run_id=? AND origin_date=?",
                (
                    output.model_artifact,
                    output.context_artifact,
                    lease.run_id,
                    lease.origin.origin_date.isoformat(),
                ),
            )

    def fail_origin(self, lease: OriginLease, error: str, *, retryable: bool) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            next_status = "QUEUED" if retryable and lease.attempt < 3 else "FAILED"
            changed = db.execute(
                "UPDATE forecast_origins SET status=?,error=? WHERE run_id=? AND "
                "origin_date=? AND status='RUNNING' AND attempt=?",
                (
                    next_status,
                    error,
                    lease.run_id,
                    lease.origin.origin_date.isoformat(),
                    lease.attempt,
                ),
            ).rowcount
            if changed != 1:
                raise StaleLeaseError("起点leaseは失効しています")
            db.execute(
                "INSERT INTO forecast_failures VALUES (?,?,?,?,?)",
                (
                    lease.run_id,
                    lease.origin.origin_date.isoformat(),
                    lease.attempt,
                    error,
                    int(retryable),
                ),
            )

    def finish_run(self, run_id: str) -> RunStatus:
        with self._connect() as db:
            states = [
                r[0]
                for r in db.execute("SELECT status FROM forecast_origins WHERE run_id=?", (run_id,))
            ]
            cancelled = self.cancellation_requested(run_id)
            status: RunStatus
            if cancelled:
                status = "CANCELLED"
            elif states and all(s == "SUCCEEDED" for s in states):
                status = "SUCCEEDED"
            elif any(s == "SUCCEEDED" for s in states):
                status = "PARTIAL"
            else:
                status = "FAILED"
            db.execute("UPDATE forecast_runs SET status=? WHERE run_id=?", (status, run_id))
            return status

    def cancellation_requested(self, run_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT cancellation_requested FROM forecast_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            return bool(row[0])

    def request_cancellation(self, run_id: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE forecast_runs SET cancellation_requested=1 WHERE run_id=?", (run_id,)
            )

    def rows(self, table: str) -> list[sqlite3.Row]:
        allowed = {
            "forecast_runs",
            "forecast_origins",
            "forecast_expectations",
            "forecast_values",
            "forecast_failures",
        }
        if table not in allowed:
            raise ValueError("table不正")
        with self._connect() as db:
            return list(db.execute(f"SELECT * FROM {table}"))
