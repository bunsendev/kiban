"""SQLite/PostgreSQL共通の原本取込台帳。"""

import sqlite3
import uuid
from pathlib import Path

from ..jobs.postgres_store import _Connection
from .contracts import ImportJob, SourceFile


class SqliteIngestionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    def enqueue(self, source_path: str) -> ImportJob:
        value = ImportJob(str(uuid.uuid4()), source_path, "QUEUED")
        with self._connect() as db:
            db.execute(
                "INSERT INTO import_jobs(import_id,source_path,status,error) VALUES (?,?,?,?)",
                (value.import_id, source_path, "QUEUED", None),
            )
        return value

    def get_job(self, import_id: str) -> ImportJob | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM import_jobs WHERE import_id=?", (import_id,)).fetchone()
            if row is None:
                return None
            counts = {
                r[0]: r[1]
                for r in db.execute(
                    "SELECT status,count(*) FROM source_files WHERE import_id=? GROUP BY status",
                    (import_id,),
                )
            }
        return ImportJob(
            row["import_id"],
            row["source_path"],
            row["status"],
            sum(counts.values()),
            counts.get("ACCEPTED", 0) + counts.get("CORRECTION_CANDIDATE", 0),
            counts.get("QUARANTINED", 0),
            counts.get("DUPLICATE", 0),
            row["error"],
        )

    def claim(self) -> ImportJob | None:
        import_id = None
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT import_id FROM import_jobs WHERE status='QUEUED' "
                "ORDER BY created_at,import_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE import_jobs SET status='RUNNING' WHERE import_id=? AND status='QUEUED'",
                (row[0],),
            )
            import_id = row[0]
        return self.get_job(import_id)

    def find_hash(self, sha256: str):
        with self._connect() as db:
            return db.execute(
                "SELECT source_file_id FROM source_files "
                "WHERE sha256=? AND status!='QUARANTINED' LIMIT 1",
                (sha256,),
            ).fetchone()

    def find_logical(self, logical_path: str):
        with self._connect() as db:
            return db.execute(
                "SELECT source_file_id FROM source_files WHERE logical_path=? "
                "AND status IN ('ACCEPTED','CORRECTION_CANDIDATE') "
                "ORDER BY created_at DESC, source_file_id DESC LIMIT 1",
                (logical_path,),
            ).fetchone()

    def record_file(self, value: SourceFile) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO source_files(source_file_id,import_id,logical_path,size_bytes,"
                "sha256,encoding,status,stored_path,duplicate_of,correction_of,error) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    value.source_file_id,
                    value.import_id,
                    value.logical_path,
                    value.size_bytes,
                    value.sha256,
                    value.encoding,
                    value.status,
                    value.stored_path,
                    value.duplicate_of,
                    value.correction_of,
                    value.error,
                ),
            )

    def finish(self, import_id: str, error: str | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE import_jobs SET status=?, error=? WHERE import_id=?",
                ("FAILED" if error else "SUCCEEDED", error, import_id),
            )

    def list_files(self, import_id: str) -> list[SourceFile]:
        with self._connect() as db:
            return [
                SourceFile(**dict(row))
                for row in db.execute(
                    "SELECT source_file_id,import_id,logical_path,size_bytes,sha256,encoding,"
                    "status,stored_path,duplicate_of,correction_of,error FROM source_files "
                    "WHERE import_id=? ORDER BY logical_path",
                    (import_id,),
                )
            ]

    def get_file(self, source_file_id: str) -> SourceFile | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT source_file_id,import_id,logical_path,size_bytes,sha256,encoding,"
                "status,stored_path,duplicate_of,correction_of,error FROM source_files "
                "WHERE source_file_id=?",
                (source_file_id,),
            ).fetchone()
            return None if row is None else SourceFile(**dict(row))


class PostgresIngestionStore(SqliteIngestionStore):
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.path = Path(".")
        self._initialize()

    def _raw_connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _connect(self):
        return _Connection(self._raw_connect())

    def _initialize(self):
        with self._raw_connect() as db:
            for statement in (
                Path(__file__).with_name("schema.sql").read_text(encoding="utf-8").split(";")
            ):
                if statement.strip():
                    db.execute(statement)

    def claim(self) -> ImportJob | None:
        import_id = None
        with self._connect() as db:
            row = db.execute(
                "SELECT import_id FROM import_jobs WHERE status='QUEUED' "
                "ORDER BY created_at,import_id FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            import_id = row[0]
            db.execute(
                "UPDATE import_jobs SET status='RUNNING' WHERE import_id=? AND status='QUEUED'",
                (import_id,),
            )
        return self.get_job(import_id)
