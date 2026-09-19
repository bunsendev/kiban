"""レビュー対応タスクと状態イベントの追記型ストア。"""

import sqlite3
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .actions import (
    ActionConflict,
    ReviewActionEvent,
    ReviewActionSnapshot,
    ReviewActionTask,
    validate_action_transition,
)


class SqliteReviewActionStore:
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
            db.executescript(Path(__file__).with_name("schema.sql").read_text("utf-8"))
            db.executescript(Path(__file__).with_name("action_schema.sql").read_text("utf-8"))

    def create(
        self, task: ReviewActionTask, event: ReviewActionEvent
    ) -> ReviewActionSnapshot:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO model_review_actions VALUES (?,?,?,?,?,?)",
                tuple(task.__dict__.values()),
            )
            self._insert_event(db, event)
        return ReviewActionSnapshot(task, event, 1)

    def get(self, action_id: str) -> ReviewActionSnapshot | None:
        with self._connect() as db:
            task = db.execute(
                "SELECT * FROM model_review_actions WHERE action_id=?", (action_id,)
            ).fetchone()
            if task is None:
                return None
            latest = self._latest(db, action_id)
            count = db.execute(
                "SELECT COUNT(*) AS count FROM model_review_action_events WHERE action_id=?",
                (action_id,),
            ).fetchone()["count"]
            return ReviewActionSnapshot(_task(task), _event(latest), count)

    def append(
        self, event: ReviewActionEvent, expected_revision: int
    ) -> ReviewActionSnapshot:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task_row = db.execute(
                f"SELECT * FROM model_review_actions WHERE action_id=?{self.lock_clause}",
                (event.action_id,),
            ).fetchone()
            if task_row is None:
                raise KeyError(event.action_id)
            latest = _event(self._latest(db, event.action_id))
            if latest.revision != expected_revision or event.revision != expected_revision + 1:
                raise ActionConflict("ほかの利用者が先に更新しました。再読み込みしてください")
            validate_action_transition(latest.status, event.status)
            self._insert_event(db, event)
            count = db.execute(
                "SELECT COUNT(*) AS count FROM model_review_action_events WHERE action_id=?",
                (event.action_id,),
            ).fetchone()["count"]
            return ReviewActionSnapshot(_task(task_row), event, count)

    def list_tasks(
        self, *, review_id: str | None = None, limit: int = 200
    ) -> list[ReviewActionSnapshot]:
        if not 1 <= limit <= 200:
            raise ValueError("limitは1以上200以下です")
        where = " WHERE a.review_id=?" if review_id else ""
        params = (review_id,) if review_id else ()
        query = f"""
            SELECT a.*, e.event_id,e.revision,e.status,e.assignee,e.due_date,
                   e.note,e.completion_evidence,e.recorded_by,e.recorded_at,
                   counts.event_count
            FROM model_review_actions a
            JOIN model_review_action_events e ON e.action_id=a.action_id
            JOIN (
              SELECT action_id,MAX(revision) AS revision,COUNT(*) AS event_count
              FROM model_review_action_events GROUP BY action_id
            ) counts ON counts.action_id=a.action_id AND counts.revision=e.revision
            {where}
            ORDER BY e.recorded_at DESC,a.action_id DESC LIMIT ?
        """
        with self._connect() as db:
            return [_snapshot(row) for row in db.execute(query, (*params, limit))]

    def list_events(
        self, *, action_id: str | None = None, limit: int = 500
    ) -> list[ReviewActionEvent]:
        if not 1 <= limit <= 500:
            raise ValueError("limitは1以上500以下です")
        where = " WHERE action_id=?" if action_id else ""
        params = (action_id,) if action_id else ()
        query = (
            "SELECT * FROM model_review_action_events"
            f"{where} ORDER BY recorded_at DESC,action_id DESC,revision DESC LIMIT ?"
        )
        with self._connect() as db:
            return [_event(row) for row in db.execute(query, (*params, limit))]

    def _latest(self, db, action_id: str):
        row = db.execute(
            "SELECT * FROM model_review_action_events WHERE action_id=? "
            f"ORDER BY revision DESC LIMIT 1{self.lock_clause}",
            (action_id,),
        ).fetchone()
        if row is None:
            raise KeyError(action_id)
        return row

    @staticmethod
    def _insert_event(db, event: ReviewActionEvent) -> None:
        db.execute(
            "INSERT INTO model_review_action_events VALUES (?,?,?,?,?,?,?,?,?,?)",
            tuple(event.__dict__.values()),
        )


class PostgresReviewActionStore(SqliteReviewActionStore):
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
            for name in ("schema.sql", "action_schema.sql"):
                for statement in Path(__file__).with_name(name).read_text("utf-8").split(";"):
                    if statement.strip():
                        db.execute(statement)


def _task(row) -> ReviewActionTask:
    values = dict(row)
    return ReviewActionTask(**{name: values[name] for name in ReviewActionTask.__annotations__})


def _event(row) -> ReviewActionEvent:
    values = dict(row)
    return ReviewActionEvent(**{name: values[name] for name in ReviewActionEvent.__annotations__})


def _snapshot(row) -> ReviewActionSnapshot:
    return ReviewActionSnapshot(_task(row), _event(row), int(row["event_count"]))
