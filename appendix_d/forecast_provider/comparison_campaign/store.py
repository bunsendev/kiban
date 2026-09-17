"""比較キャンペーンのSQLite/PostgreSQL台帳。"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import CampaignEntry, CampaignFinalization, ComparisonCampaign


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteComparisonCampaignStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    @staticmethod
    def _campaign(row) -> ComparisonCampaign:
        values = dict(row)
        value = values["created_at"]
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            values["created_at"] = value.astimezone(UTC).isoformat()
        return ComparisonCampaign(**values)

    @staticmethod
    def _finalization(row) -> CampaignFinalization:
        values = dict(row)
        for name in ("requested_at", "started_at", "finished_at"):
            value = values.get(name)
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                values[name] = value.astimezone(UTC).isoformat()
        return CampaignFinalization(**values)

    def reserve(
        self, request_key_hash: str, snapshot_id: str, requested_by: str, purpose: str,
        model_keys: str, mode: str = "primary", horizon: int | None = None,
        policy_version: str = "evaluation-v2.9",
    ) -> tuple[ComparisonCampaign, bool]:
        current = self.get_by_request(requested_by, request_key_hash)
        if current is not None:
            if (
                current.snapshot_id != snapshot_id
                or current.purpose != purpose
                or current.model_keys != model_keys
                or self._definition(current.campaign_id) != (mode, horizon, policy_version)
            ):
                raise ValueError(
                    "同じrequest_keyを異なる条件では再利用できません"
                ) from None
            return current, False
        value = ComparisonCampaign(
            str(uuid.uuid4()), request_key_hash, snapshot_id, requested_by, purpose,
            model_keys, _now(),
        )
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO comparison_campaigns VALUES (?,?,?,?,?,?,?)",
                    tuple(value.__dict__.values()),
                )
                db.execute(
                    "INSERT INTO comparison_campaign_finalizations("
                    "campaign_id,mode,horizon,policy_version,status,requested_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (value.campaign_id, mode, horizon, policy_version, "WAITING", value.created_at),
                )
        except Exception:
            current = self.get_by_request(requested_by, request_key_hash)
            if current is None:
                raise
            if (
                current.snapshot_id != snapshot_id
                or current.purpose != purpose
                or current.model_keys != model_keys
                or self._definition(current.campaign_id) != (mode, horizon, policy_version)
            ):
                raise ValueError(
                    "同じrequest_keyを異なる条件では再利用できません"
                ) from None
            return current, False
        return value, True

    def _definition(self, campaign_id: str) -> tuple[str, int | None, str] | None:
        value = self.get_finalization(campaign_id)
        return None if value is None else (value.mode, value.horizon, value.policy_version)

    def put_entry(self, value: CampaignEntry) -> CampaignEntry:
        with self._connect() as db:
            db.execute(
                "INSERT INTO comparison_campaign_entries VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(campaign_id,provider_id,model_id) DO NOTHING",
                tuple(value.__dict__.values()),
            )
            row = db.execute(
                "SELECT * FROM comparison_campaign_entries WHERE campaign_id=? "
                "AND provider_id=? AND model_id=?",
                (value.campaign_id, value.provider_id, value.model_id),
            ).fetchone()
        current = CampaignEntry(**dict(row))
        if current != value:
            raise ValueError("同じキャンペーン項目の内容は変更できません")
        return current

    def get(self, campaign_id: str) -> ComparisonCampaign | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM comparison_campaigns WHERE campaign_id=?", (campaign_id,)
            ).fetchone()
        return None if row is None else self._campaign(row)

    def get_by_request(self, requested_by: str, request_key_hash: str):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM comparison_campaigns "
                "WHERE requested_by=? AND request_key_hash=?",
                (requested_by, request_key_hash),
            ).fetchone()
        return None if row is None else self._campaign(row)

    def list(self, *, limit: int = 100) -> list[ComparisonCampaign]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM comparison_campaigns "
                "ORDER BY created_at DESC,campaign_id DESC LIMIT ?",
                (limit,),
            )
            return [self._campaign(row) for row in rows]

    def list_entries(self, campaign_id: str) -> list[CampaignEntry]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM comparison_campaign_entries WHERE campaign_id=? "
                "ORDER BY provider_id,model_id",
                (campaign_id,),
            )
            return [CampaignEntry(**dict(row)) for row in rows]

    def get_finalization(self, campaign_id: str) -> CampaignFinalization | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM comparison_campaign_finalizations WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
        return None if row is None else self._finalization(row)

    def claim_finalization(self) -> CampaignFinalization | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT campaign_id FROM comparison_campaign_finalizations "
                "WHERE status='WAITING' "
                "ORDER BY COALESCE(started_at,requested_at),campaign_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            campaign_id = row[0]
            changed = db.execute(
                "UPDATE comparison_campaign_finalizations SET status='RUNNING',started_at=?,"
                "finished_at=NULL,error_code=NULL,error_message=NULL "
                "WHERE campaign_id=? AND status='WAITING'",
                (_now(), campaign_id),
            ).rowcount
            if changed != 1:
                return None
        return self.get_finalization(campaign_id)

    def defer_finalization(self, campaign_id: str) -> None:
        self._transition(
            campaign_id,
            "UPDATE comparison_campaign_finalizations SET status='WAITING',started_at=? "
            "WHERE campaign_id=? AND status='RUNNING'",
            (_now(), campaign_id),
            "RUNNINGの自動比較だけを待機へ戻せます",
        )

    def complete_finalization(self, campaign_id: str, comparison_id: str) -> None:
        self._transition(
            campaign_id,
            "UPDATE comparison_campaign_finalizations SET status='SUCCEEDED',finished_at=?,"
            "comparison_id=?,error_code=NULL,error_message=NULL "
            "WHERE campaign_id=? AND status='RUNNING'",
            (_now(), comparison_id, campaign_id),
            "RUNNINGの自動比較だけを完了できます",
        )

    def fail_finalization(
        self, campaign_id: str, error_code: str, error_message: str
    ) -> None:
        self._transition(
            campaign_id,
            "UPDATE comparison_campaign_finalizations SET status='FAILED',finished_at=?,"
            "comparison_id=NULL,error_code=?,error_message=? "
            "WHERE campaign_id=? AND status='RUNNING'",
            (_now(), error_code[:80], error_message[:500], campaign_id),
            "RUNNINGの自動比較だけを失敗にできます",
        )

    def retry_finalization(self, campaign_id: str) -> CampaignFinalization:
        self._transition(
            campaign_id,
            "UPDATE comparison_campaign_finalizations SET status='WAITING',started_at=NULL,"
            "finished_at=NULL,comparison_id=NULL,error_code=NULL,error_message=NULL "
            "WHERE campaign_id=? AND status='FAILED'",
            (campaign_id,),
            "FAILEDの自動比較だけを再実行できます",
        )
        value = self.get_finalization(campaign_id)
        assert value is not None
        return value

    def _transition(self, campaign_id: str, sql: str, params: tuple, message: str) -> None:
        with self._connect() as db:
            changed = db.execute(sql, params).rowcount
        if changed != 1:
            raise ValueError(message)


class PostgresComparisonCampaignStore(SqliteComparisonCampaignStore):
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.path = Path(".")
        self._initialize()

    def _raw_connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _connect(self):
        return _Connection(self._raw_connect())

    def _initialize(self) -> None:
        with self._raw_connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(26091702)")
            sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            for statement in sql.split(";"):
                if statement.strip():
                    db.execute(statement)

    def claim_finalization(self) -> CampaignFinalization | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT campaign_id FROM comparison_campaign_finalizations "
                "WHERE status='WAITING' ORDER BY COALESCE(started_at,requested_at),campaign_id "
                "FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            campaign_id = row[0]
            db.execute(
                "UPDATE comparison_campaign_finalizations SET status='RUNNING',started_at=?,"
                "finished_at=NULL,error_code=NULL,error_message=NULL "
                "WHERE campaign_id=? AND status='WAITING'",
                (_now(), campaign_id),
            )
        return self.get_finalization(campaign_id)
