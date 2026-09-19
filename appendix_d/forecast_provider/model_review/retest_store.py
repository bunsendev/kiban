"""追加テストのリンクと対応履歴を同一transactionで更新する。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .actions import TERMINAL_STATUSES, ActionConflict, make_review_action_event
from .retests import ReviewRetest


class SqliteReviewRetestStore:
    lock_clause = ""

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
            for name in ("schema.sql", "action_schema.sql", "retest_schema.sql"):
                db.executescript(Path(__file__).with_name(name).read_text("utf-8"))

    def get_by_request(self, action_id: str, request_key_hash: str) -> ReviewRetest | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM model_review_retests WHERE action_id=? AND request_key_hash=?",
                (action_id, request_key_hash),
            ).fetchone()
        return None if row is None else _retest(row)

    def get_by_campaign(self, campaign_id: str) -> ReviewRetest | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM model_review_retests WHERE campaign_id=?", (campaign_id,)
            ).fetchone()
        return None if row is None else _retest(row)

    def reserve_and_start(self, value: ReviewRetest, expected_revision: int) -> ReviewRetest:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM model_review_retests WHERE action_id=? AND request_key_hash=?",
                (value.action_id, value.request_key_hash),
            ).fetchone()
            if existing is not None:
                saved = _retest(existing)
                _same_request(saved, value)
                return saved
            latest = self._latest_event(db, value.action_id)
            if latest["revision"] != expected_revision:
                raise ActionConflict("ほかの利用者が先に更新しました。再読み込みしてください")
            if latest["status"] not in {"OPEN", "BLOCKED"}:
                raise ActionConflict("未着手または保留の追加テストだけを開始できます")
            db.execute(
                "INSERT INTO model_review_retests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(value.__dict__.values()),
            )
            event = make_review_action_event(
                value.action_id,
                expected_revision + 1,
                "IN_PROGRESS",
                latest["assignee"],
                date.fromisoformat(latest["due_date"]),
                f"追加テストを開始しました（campaign_id={value.campaign_id}）",
                None,
                value.requested_by,
                latest["status"],
            )
            db.execute(
                "INSERT INTO model_review_action_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                tuple(event.__dict__.values()),
            )
        return value

    def list(self, *, action_id: str | None = None, limit: int = 200) -> list[ReviewRetest]:
        if not 1 <= limit <= 200:
            raise ValueError("limitは1以上200以下です")
        where = " WHERE action_id=?" if action_id else ""
        params = (action_id,) if action_id else ()
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM model_review_retests"
                f"{where} ORDER BY requested_at DESC,retest_id DESC LIMIT ?",
                (*params, limit),
            )
            return [_retest(row) for row in rows]

    def list_pending(self, *, limit: int = 200) -> list[ReviewRetest]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM model_review_retests WHERE outcome_status IS NULL "
                "ORDER BY requested_at,retest_id LIMIT ?",
                (limit,),
            )
            return [_retest(row) for row in rows]

    def finalize(
        self,
        campaign_id: str,
        outcome_status: str,
        *,
        comparison_id: str | None = None,
        error_message: str | None = None,
        actor: str = "system:comparison-campaign-worker",
    ) -> bool:
        if outcome_status not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("追加テスト結果が不正です")
        if (outcome_status == "SUCCEEDED") != (comparison_id is not None):
            raise ValueError("成功時はcomparison_idが必要です")
        if (outcome_status == "FAILED") != (error_message is not None):
            raise ValueError("失敗時はerror_messageが必要です")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                f"SELECT * FROM model_review_retests WHERE campaign_id=?{self.lock_clause}",
                (campaign_id,),
            ).fetchone()
            if row is None or row["outcome_status"] is not None:
                return False
            latest = self._latest_event(db, row["action_id"])
            if latest["status"] not in TERMINAL_STATUSES:
                success = outcome_status == "SUCCEEDED"
                event = make_review_action_event(
                    row["action_id"],
                    latest["revision"] + 1,
                    "COMPLETED" if success else "BLOCKED",
                    latest["assignee"],
                    date.fromisoformat(latest["due_date"]),
                    (
                        f"追加テストが完了しました（campaign_id={campaign_id}）"
                        if success
                        else f"追加テストに失敗しました: {error_message}"
                    ),
                    (
                        f"campaign_id={campaign_id}; comparison_id={comparison_id}"
                        if success
                        else None
                    ),
                    actor,
                    latest["status"],
                )
                db.execute(
                    "INSERT INTO model_review_action_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                    tuple(event.__dict__.values()),
                )
            finished_at = datetime.now(UTC).isoformat()
            db.execute(
                "UPDATE model_review_retests SET outcome_status=?,comparison_id=?,"
                "error_message=?,finished_at=? WHERE campaign_id=?",
                (outcome_status, comparison_id, error_message, finished_at, campaign_id),
            )
        return True

    def _latest_event(self, db, action_id: str):
        row = db.execute(
            "SELECT * FROM model_review_action_events WHERE action_id=? "
            f"ORDER BY revision DESC LIMIT 1{self.lock_clause}",
            (action_id,),
        ).fetchone()
        if row is None:
            raise KeyError(action_id)
        return row


class PostgresReviewRetestStore(SqliteReviewRetestStore):
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
            for name in ("schema.sql", "action_schema.sql", "retest_schema.sql"):
                for statement in Path(__file__).with_name(name).read_text("utf-8").split(";"):
                    if statement.strip():
                        db.execute(statement)


def _retest(row) -> ReviewRetest:
    values = dict(row)
    return ReviewRetest(**{name: values[name] for name in ReviewRetest.__annotations__})


def _same_request(saved: ReviewRetest, requested: ReviewRetest) -> None:
    names = ("source_campaign_id", "target_snapshot_id", "campaign_id", "requested_by")
    if any(getattr(saved, name) != getattr(requested, name) for name in names):
        raise ValueError("同じrequest keyを異なる追加テストには使えません")
