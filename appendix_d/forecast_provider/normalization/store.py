"""出荷正規化台帳のSQLite/PostgreSQL実装。"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .contracts import (
    ColumnMapping,
    NormalizationJob,
    Reconciliation,
    ShipmentRow,
    SourceSelection,
)
from .quality import build_quality


class SqliteNormalizationStore:
    def __init__(self, path: Path):
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

    def put_mapping(self, value: ColumnMapping):
        encoded = json.dumps(
            value.definition, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self._connect() as db:
            db.execute(
                "INSERT INTO column_mappings VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                (value.mapping_id, value.format_version, value.content_hash, encoded),
            )
            row = db.execute(
                "SELECT * FROM column_mappings WHERE mapping_id=?", (value.mapping_id,)
            ).fetchone()
        if self._mapping(row) != value:
            raise ValueError("同じmapping_idの内容は変更できません")

    def get_mapping(self, mapping_id: str) -> ColumnMapping | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM column_mappings WHERE mapping_id=?", (mapping_id,)
            ).fetchone()
            return None if row is None else self._mapping(row)

    @staticmethod
    def _mapping(row):
        return ColumnMapping(
            row["mapping_id"],
            row["format_version"],
            row["content_hash"],
            json.loads(row["definition_json"]),
        )

    def select_source(
        self,
        logical_path: str,
        source_file_id: str,
        decision_version: str,
        decided_by: str,
        reason: str,
    ) -> str:
        if not all((logical_path, source_file_id, decision_version, decided_by, reason)):
            raise ValueError("訂正版採用の版・担当者・理由は必須です")
        selection_id = str(uuid.uuid4())
        with self._connect() as db:
            row = db.execute(
                "SELECT logical_path,status FROM source_files WHERE source_file_id=?",
                (source_file_id,),
            ).fetchone()
            if (
                row is None
                or row[0] != logical_path
                or row[1] not in {"ACCEPTED", "CORRECTION_CANDIDATE"}
            ):
                raise ValueError("採用できる原本ではありません")
            existing = db.execute(
                "SELECT selection_id FROM source_file_selections "
                "WHERE logical_path=? AND decision_version=?",
                (logical_path, decision_version),
            ).fetchone()
            if existing is not None:
                raise ValueError("同じlogical pathとdecision versionは再利用できません")
            db.execute(
                "INSERT INTO source_file_selections("
                "selection_id,logical_path,source_file_id,decision_version,decided_by,reason,"
                "decided_at) VALUES (?,?,?,?,?,?,?)",
                (
                    selection_id,
                    logical_path,
                    source_file_id,
                    decision_version,
                    decided_by,
                    reason,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return selection_id

    def list_selections(self, logical_path: str | None = None) -> list[SourceSelection]:
        sql = (
            "SELECT selection_id,logical_path,source_file_id,decision_version,decided_by,"
            "reason,decided_at FROM source_file_selections"
        )
        params = ()
        if logical_path is not None:
            sql += " WHERE logical_path=?"
            params = (logical_path,)
        sql += " ORDER BY decided_at,selection_id"
        with self._connect() as db:
            return [SourceSelection(**dict(row)) for row in db.execute(sql, params)]

    def _selected(self, source_file_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT status,logical_path FROM source_files WHERE source_file_id=?",
                (source_file_id,),
            ).fetchone()
            if row is None:
                raise ValueError("原本が見つかりません")
            if row[0] not in {"ACCEPTED", "CORRECTION_CANDIDATE"}:
                return False
            latest = db.execute(
                "SELECT source_file_id FROM source_file_selections WHERE logical_path=? "
                "ORDER BY decided_at DESC,selection_id DESC LIMIT 1",
                (row[1],),
            ).fetchone()
            return row[0] == "ACCEPTED" if latest is None else latest[0] == source_file_id

    def enqueue(self, source_file_id: str, mapping_id: str) -> NormalizationJob:
        if not self._selected(source_file_id):
            raise ValueError("訂正版候補は明示採用後だけ正規化できます")
        if self.get_mapping(mapping_id) is None:
            raise ValueError("列mappingが見つかりません")
        with self._connect() as db:
            existing = db.execute(
                "SELECT normalization_id FROM normalization_jobs "
                "WHERE source_file_id=? AND mapping_id=?",
                (source_file_id, mapping_id),
            ).fetchone()
        if existing is not None:
            return self.get_job(existing[0])
        value = NormalizationJob(str(uuid.uuid4()), source_file_id, mapping_id, "QUEUED")
        with self._connect() as db:
            db.execute(
                "INSERT INTO normalization_jobs("
                "normalization_id,source_file_id,mapping_id,status,error"
                ") VALUES (?,?,?,?,?)",
                (value.normalization_id, source_file_id, mapping_id, "QUEUED", None),
            )
        return value

    def claim(self) -> NormalizationJob | None:
        normalization_id = None
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT normalization_id FROM normalization_jobs WHERE status='QUEUED' "
                "ORDER BY created_at,normalization_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            normalization_id = row[0]
            db.execute(
                "UPDATE normalization_jobs SET status='RUNNING' "
                "WHERE normalization_id=? AND status='QUEUED'",
                (normalization_id,),
            )
        return self.get_job(normalization_id)

    def get_job(self, normalization_id: str) -> NormalizationJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM normalization_jobs WHERE normalization_id=?", (normalization_id,)
            ).fetchone()
            if row is None:
                return None
            counts = {
                item[0]: item[1]
                for item in db.execute(
                    "SELECT status,count(*) FROM shipment_rows "
                    "WHERE normalization_id=? GROUP BY status",
                    (normalization_id,),
                )
            }
        return NormalizationJob(
            row["normalization_id"],
            row["source_file_id"],
            row["mapping_id"],
            row["status"],
            sum(counts.values()),
            counts.get("ACCEPTED", 0),
            counts.get("QUARANTINED", 0),
            row["error"],
        )

    def complete(self, normalization_id: str, rows: list[ShipmentRow], value: Reconciliation):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "INSERT INTO shipment_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        r.normalization_id,
                        r.source_file_id,
                        r.row_number,
                        r.center_id,
                        r.shipment_date,
                        r.raw_jan,
                        r.raw_product_name,
                        None if r.quantity is None else str(r.quantity),
                        r.unit,
                        r.row_type,
                        r.available_at,
                        r.status,
                        r.error,
                    )
                    for r in rows
                ],
            )
            db.execute(
                "INSERT INTO quantity_reconciliations VALUES (?,?,?,?,?)",
                (
                    value.normalization_id,
                    str(value.parseable_quantity),
                    str(value.accepted_quantity),
                    str(value.quarantined_quantity),
                    str(value.unexplained_quantity),
                ),
            )
            db.execute(
                "UPDATE normalization_jobs SET status='SUCCEEDED' WHERE normalization_id=?",
                (normalization_id,),
            )

    def fail(self, normalization_id: str, error: str):
        with self._connect() as db:
            db.execute(
                "UPDATE normalization_jobs SET status='FAILED',error=? WHERE normalization_id=?",
                (error, normalization_id),
            )

    def results(self, normalization_id: str) -> dict | None:
        job = self.get_job(normalization_id)
        if job is None:
            return None
        with self._connect() as db:
            rows = [
                dict(x)
                for x in db.execute(
                    "SELECT * FROM shipment_rows WHERE normalization_id=? ORDER BY row_number",
                    (normalization_id,),
                )
            ]
            rec = db.execute(
                "SELECT * FROM quantity_reconciliations WHERE normalization_id=?",
                (normalization_id,),
            ).fetchone()
        return {**job.__dict__, "rows": rows, "reconciliation": None if rec is None else dict(rec)}

    def quality(self) -> dict:
        with self._connect() as db:
            return build_quality(db)
