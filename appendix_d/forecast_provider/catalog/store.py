"""CatalogのSQLite実装とPostgreSQL実装。"""

import json
import sqlite3
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import ExperimentRecord, SnapshotRecord


class SqliteCatalogStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(_schema_path().read_text(encoding="utf-8"))

    def put_snapshot(self, record: SnapshotRecord) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO dataset_snapshots VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                (
                    record.snapshot_id,
                    record.format_version,
                    record.content_hash,
                    _json(record.manifest),
                    1,
                ),
            )
            row = db.execute(
                "SELECT * FROM dataset_snapshots WHERE snapshot_id=?", (record.snapshot_id,)
            ).fetchone()
            current = _snapshot(row)
            if current != record:
                raise ValueError("同じsnapshot_idの内容は変更できません")

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM dataset_snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
            return None if row is None else _snapshot(row)

    def list_snapshots(self, *, limit: int = 100) -> list[SnapshotRecord]:
        _validate_limit(limit)
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM dataset_snapshots ORDER BY snapshot_id DESC LIMIT ?", (limit,)
            )
            return [_snapshot(row) for row in rows]

    def put_experiment(self, record: ExperimentRecord) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO experiments VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                (
                    record.experiment_id,
                    record.format_version,
                    record.condition_fingerprint,
                    record.snapshot_id,
                    _json(record.definition),
                ),
            )
            row = db.execute(
                "SELECT * FROM experiments WHERE experiment_id=?", (record.experiment_id,)
            ).fetchone()
            current = _experiment(row)
            if current != record:
                raise ValueError("同じexperiment_idの内容は変更できません")

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM experiments WHERE experiment_id=?", (experiment_id,)
            ).fetchone()
            return None if row is None else _experiment(row)

    def list_experiments(
        self, *, snapshot_id: str | None = None, limit: int = 100
    ) -> list[ExperimentRecord]:
        _validate_limit(limit)
        query = "SELECT * FROM experiments"
        params: tuple[object, ...]
        if snapshot_id is None:
            params = (limit,)
        else:
            query += " WHERE snapshot_id=?"
            params = (snapshot_id, limit)
        query += " ORDER BY experiment_id DESC LIMIT ?"
        with self._connect() as db:
            return [_experiment(row) for row in db.execute(query, params)]


class PostgresCatalogStore(SqliteCatalogStore):
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._initialize()

    def _raw_connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL利用にはpsycopgが必要です") from exc
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _connect(self):
        return _Connection(self._raw_connect())

    def _initialize(self) -> None:
        with self._raw_connect() as db:
            for statement in _schema_path().read_text(encoding="utf-8").split(";"):
                if statement.strip():
                    db.execute(statement)


def _schema_path() -> Path:
    return Path(__file__).with_name("schema.sql")


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limitは1以上200以下です")


def _snapshot(row) -> SnapshotRecord:
    return SnapshotRecord(
        row["snapshot_id"],
        row["format_version"],
        row["content_hash"],
        json.loads(row["manifest_json"]),
    )


def _experiment(row) -> ExperimentRecord:
    return ExperimentRecord(
        row["experiment_id"],
        row["format_version"],
        row["condition_fingerprint"],
        row["snapshot_id"],
        json.loads(row["definition_json"]),
    )
