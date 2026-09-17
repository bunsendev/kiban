"""SQLiteによる参照用run台帳。各起点の結果を一transactionで確定する。"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, date, datetime, timedelta
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
    RunSnapshot,
    RunStatus,
)
from .results import failure_result, forecast_result, origin_result


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
        migration = Path(__file__).with_name("migrations") / "001_run_ledger_sqlite.sql"
        with self._connect() as db:
            db.executescript(migration.read_text(encoding="utf-8"))

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
            db.execute("UPDATE forecast_runs SET status='RUNNING' WHERE run_id=?", (run_id,))

    def claim_next_origin(
        self, run_id: str, worker_id: str, lease_seconds: int
    ) -> OriginLease | None:
        if not worker_id or lease_seconds <= 0:
            raise ValueError("worker_idと正のlease_secondsが必要です")
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
            token = str(uuid.uuid4())
            leased_until = datetime.now(UTC) + timedelta(seconds=lease_seconds)
            db.execute(
                "UPDATE forecast_origins SET status='RUNNING',attempt=?,error=NULL,"
                "worker_id=?,lease_token=?,leased_until=? "
                "WHERE run_id=? AND origin_date=?",
                (attempt, worker_id, token, leased_until.isoformat(), run_id, row["origin_date"]),
            )
            origin = OriginDefinition(
                date.fromisoformat(row["origin_date"]), datetime.fromisoformat(row["cutoff_at"])
            )
            return OriginLease(run_id, origin, attempt, worker_id, token, leased_until)

    def heartbeat(self, lease: OriginLease, lease_seconds: int) -> OriginLease:
        if lease_seconds <= 0:
            raise ValueError("lease_secondsは正数です")
        leased_until = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        with self._connect() as db:
            changed = db.execute(
                "UPDATE forecast_origins SET leased_until=? WHERE run_id=? AND origin_date=? "
                "AND status='RUNNING' AND attempt=? AND worker_id=? AND lease_token=?",
                (
                    leased_until.isoformat(),
                    lease.run_id,
                    lease.origin.origin_date.isoformat(),
                    lease.attempt,
                    lease.worker_id,
                    lease.lease_token,
                ),
            ).rowcount
            if changed != 1:
                raise StaleLeaseError("起点leaseは失効しています")
        return OriginLease(
            lease.run_id,
            lease.origin,
            lease.attempt,
            lease.worker_id,
            lease.lease_token,
            leased_until,
        )

    def reclaim_expired(self, run_id: str, *, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        with self._connect() as db:
            return db.execute(
                "UPDATE forecast_origins SET status='QUEUED',worker_id=NULL,lease_token=NULL,"
                "leased_until=NULL WHERE run_id=? AND status='RUNNING' AND leased_until<=?",
                (run_id, now.isoformat()),
            ).rowcount

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
                "SELECT status,attempt,worker_id,lease_token FROM forecast_origins "
                "WHERE run_id=? AND origin_date=?",
                (lease.run_id, lease.origin.origin_date.isoformat()),
            ).fetchone()
            if (
                row is None
                or row["status"] != "RUNNING"
                or row["attempt"] != lease.attempt
                or row["worker_id"] != lease.worker_id
                or row["lease_token"] != lease.lease_token
            ):
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
                "context_artifact=?,worker_id=NULL,lease_token=NULL,leased_until=NULL "
                "WHERE run_id=? AND origin_date=?",
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
                "origin_date=? AND status='RUNNING' AND attempt=? AND worker_id=? "
                "AND lease_token=?",
                (
                    next_status,
                    error,
                    lease.run_id,
                    lease.origin.origin_date.isoformat(),
                    lease.attempt,
                    lease.worker_id,
                    lease.lease_token,
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
                    retryable,
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
            elif any(s in ("QUEUED", "RUNNING") for s in states):
                status = "RUNNING"
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
                "UPDATE forecast_runs SET cancellation_requested=1,"
                "status=CASE WHEN status='QUEUED' THEN 'CANCELLED' ELSE status END "
                "WHERE run_id=?",
                (run_id,),
            )

    def get_run(self, run_id: str) -> RunSnapshot | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM forecast_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            counts = {
                item["status"]: item["count"]
                for item in db.execute(
                    "SELECT status,COUNT(*) AS count FROM forecast_origins "
                    "WHERE run_id=? GROUP BY status",
                    (run_id,),
                )
            }
            failures = db.execute(
                "SELECT COUNT(*) AS count FROM forecast_failures WHERE run_id=?", (run_id,)
            ).fetchone()
            return RunSnapshot(
                row["run_id"],
                row["experiment_id"],
                row["condition_fingerprint"],
                row["status"],
                bool(row["cancellation_requested"]),
                counts,
                failures["count"],
                row["provider_id"],
                row["model_name"],
            )

    def list_runs(
        self, *, limit: int = 100, status: RunStatus | None = None
    ) -> list[RunSnapshot]:
        if not 1 <= limit <= 200:
            raise ValueError("limitは1以上200以下です")
        allowed = {"QUEUED", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"}
        if status is not None and status not in allowed:
            raise ValueError("run statusが不正です")
        sql, params = "SELECT run_id FROM forecast_runs", []
        if status is not None:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY run_id LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            run_ids = [row["run_id"] for row in db.execute(sql, params)]
        return [snapshot for run_id in run_ids if (snapshot := self.get_run(run_id))]

    def list_runnable_runs(self, provider_id: str) -> tuple[tuple[str, str], ...]:
        if not provider_id or not provider_id.strip():
            raise ValueError("provider_idは空にできません")
        with self._connect() as db:
            return tuple(
                (row["run_id"], row["condition_fingerprint"])
                for row in db.execute(
                    "SELECT run_id,condition_fingerprint FROM forecast_runs "
                    "WHERE status IN ('QUEUED','RUNNING') "
                    "AND cancellation_requested=0 AND provider_id=? ORDER BY run_id",
                    (provider_id,),
                )
            )

    def count_active_runs_by_provider(self) -> dict[str, dict[str, int]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT provider_id,status,COUNT(*) AS count FROM forecast_runs "
                "WHERE status IN ('QUEUED','RUNNING') GROUP BY provider_id,status "
                "ORDER BY provider_id,status"
            )
            result: dict[str, dict[str, int]] = {}
            for row in rows:
                result.setdefault(row["provider_id"], {})[row["status"]] = row["count"]
            return result

    def get_model_artifact(
        self,
        run_id: str,
        origin_from: date | None = None,
        origin_before: date | None = None,
    ) -> str | None:
        if (origin_from is None) != (origin_before is None):
            raise ValueError("origin期間は開始と終了を同時に指定します")
        condition = ""
        params: tuple[object, ...] = (run_id,)
        if origin_from is not None and origin_before is not None:
            if origin_from >= origin_before:
                raise ValueError("origin期間が不正です")
            condition = "AND origin_date>=? AND origin_date<? "
            params = (run_id, origin_from.isoformat(), origin_before.isoformat())
        with self._connect() as db:
            row = db.execute(
                "SELECT model_artifact FROM forecast_origins WHERE run_id=? "
                "AND status='SUCCEEDED' AND model_artifact IS NOT NULL "
                + condition
                + "ORDER BY origin_date LIMIT 1",
                params,
            ).fetchone()
            return None if row is None else row["model_artifact"]

    def get_run_results(self, run_id: str) -> dict | None:
        if self.get_run(run_id) is None:
            return None
        with self._connect() as db:
            return {
                "origins": [
                    origin_result(row)
                    for row in db.execute(
                        "SELECT origin_date,cutoff_at,status,attempt,model_artifact,"
                        "context_artifact,error FROM forecast_origins WHERE run_id=? "
                        "ORDER BY origin_date",
                        (run_id,),
                    )
                ],
                "values": [
                    forecast_result(row)
                    for row in db.execute(
                        "SELECT unique_id,origin_date,target_date,horizon,forecast_kind,"
                        "quantile,yhat_raw,yhat FROM forecast_values WHERE run_id=? "
                        "ORDER BY origin_date,unique_id,target_date,forecast_kind,quantile",
                        (run_id,),
                    )
                ],
                "failures": [
                    failure_result(row)
                    for row in db.execute(
                        "SELECT origin_date,attempt,error,retryable FROM forecast_failures "
                        "WHERE run_id=? ORDER BY origin_date,attempt",
                        (run_id,),
                    )
                ],
            }

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
