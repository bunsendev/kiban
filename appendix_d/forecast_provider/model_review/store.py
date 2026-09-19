"""モデル精度変化レビューのSQLite/PostgreSQL追記型台帳。"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import ModelDriftReview


class SqliteModelReviewStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text("utf-8"))

    def put(self, value: ModelDriftReview) -> ModelDriftReview:
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO model_drift_reviews VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        value.review_id,
                        value.comparison_profile_id,
                        value.decision_version,
                        value.conclusion,
                        value.reviewed_by,
                        value.reason,
                        value.action,
                        value.evidence_sha256,
                        json.dumps(
                            value.evidence,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ),
                        value.reviewed_at,
                    ),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper() or "DUPLICATE" in str(exc).upper():
                raise ValueError("同じ比較プロフィールと判断版は変更できません") from exc
            raise
        return value

    def get(self, review_id: str) -> ModelDriftReview | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM model_drift_reviews WHERE review_id=?",
                (review_id,),
            ).fetchone()
            return None if row is None else _record(row)

    def list(
        self, *, comparison_profile_id: str | None = None, limit: int = 200
    ) -> list[ModelDriftReview]:
        if not 1 <= limit <= 200:
            raise ValueError("limitは1以上200以下です")
        sql = "SELECT * FROM model_drift_reviews"
        params: tuple = ()
        if comparison_profile_id is not None:
            sql += " WHERE comparison_profile_id=?"
            params = (comparison_profile_id,)
        sql += " ORDER BY reviewed_at DESC,review_id DESC LIMIT ?"
        with self._connect() as db:
            return [_record(row) for row in db.execute(sql, (*params, limit))]


class PostgresModelReviewStore(SqliteModelReviewStore):
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
        schema = Path(__file__).with_name("schema.sql").read_text("utf-8")
        with self._raw_connect() as db:
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)


def _record(row) -> ModelDriftReview:
    values = dict(row)
    reviewed_at = values["reviewed_at"]
    if isinstance(reviewed_at, datetime):
        if reviewed_at.tzinfo is None:
            reviewed_at = reviewed_at.replace(tzinfo=UTC)
        values["reviewed_at"] = reviewed_at.astimezone(UTC).isoformat()
    values["evidence"] = json.loads(values.pop("evidence_json"))
    return ModelDriftReview(**values)
