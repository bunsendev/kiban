"""比較キャンペーンのSQLite/PostgreSQL台帳。"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import CampaignEntry, ComparisonCampaign


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

    def reserve(
        self, request_key_hash: str, snapshot_id: str, requested_by: str, purpose: str,
        model_keys: str,
    ) -> tuple[ComparisonCampaign, bool]:
        current = self.get_by_request(requested_by, request_key_hash)
        if current is not None:
            if (
                current.snapshot_id != snapshot_id
                or current.purpose != purpose
                or current.model_keys != model_keys
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
                db.execute(
                    "INSERT INTO comparison_campaigns VALUES (?,?,?,?,?,?,?)",
                    tuple(value.__dict__.values()),
                )
        except Exception:
            current = self.get_by_request(requested_by, request_key_hash)
            if current is None:
                raise
            if (
                current.snapshot_id != snapshot_id
                or current.purpose != purpose
                or current.model_keys != model_keys
            ):
                raise ValueError(
                    "同じrequest_keyを異なる条件では再利用できません"
                ) from None
            return current, False
        return value, True

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
