"""比較CSVと採用判断のSQLite台帳。"""

import sqlite3
from dataclasses import replace
from pathlib import Path

from .contracts import AdoptionRecord, ExportRecord
from .records import adoption_from_row, encode_json, export_from_row


class SqliteReportingStore:
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

    def put_export(self, value: ExportRecord) -> ExportRecord:
        with self._connect() as db:
            db.execute(
                "INSERT INTO report_exports VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (
                    value.export_id,
                    value.format_version,
                    value.condition_fingerprint,
                    value.comparison_id,
                    value.export_version,
                    value.baseline_run_id,
                    value.requested_by,
                    value.output_uri,
                    value.output_sha256,
                    value.row_count,
                    value.created_at,
                ),
            )
        current = self.get_export(value.export_id)
        if current is None or replace(current, created_at=value.created_at) != value:
            raise ValueError("同じexport IDまたは版の内容は変更できません")
        return current

    def get_export(self, export_id: str) -> ExportRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM report_exports WHERE export_id=?", (export_id,)
            ).fetchone()
            return None if row is None else export_from_row(row)

    def list_exports(self, comparison_id: str | None = None) -> list[ExportRecord]:
        sql, params = "SELECT * FROM report_exports", ()
        if comparison_id is not None:
            sql += " WHERE comparison_id=?"
            params = (comparison_id,)
        sql += " ORDER BY created_at DESC,export_id"
        with self._connect() as db:
            return [export_from_row(row) for row in db.execute(sql, params)]

    def put_adoption(self, value: AdoptionRecord) -> AdoptionRecord:
        with self._connect() as db:
            db.execute(
                "INSERT INTO adoption_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (
                    value.adoption_id,
                    value.format_version,
                    value.condition_fingerprint,
                    value.adoption_version,
                    value.comparison_id,
                    value.acceptance_case_id,
                    value.decision,
                    value.selected_run_id,
                    value.fallback_run_id,
                    encode_json(value.target),
                    value.decided_by,
                    value.reason,
                    value.decided_at,
                ),
            )
        current = self.get_adoption(value.adoption_id)
        if current is None or replace(current, decided_at=value.decided_at) != value:
            raise ValueError("同じadoption IDまたは版の内容は変更できません")
        return current

    def get_adoption(self, adoption_id: str) -> AdoptionRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM adoption_records WHERE adoption_id=?", (adoption_id,)
            ).fetchone()
            return None if row is None else adoption_from_row(row)

    def list_adoptions(self, comparison_id: str | None = None) -> list[AdoptionRecord]:
        sql, params = "SELECT * FROM adoption_records", ()
        if comparison_id is not None:
            sql += " WHERE comparison_id=?"
            params = (comparison_id,)
        sql += " ORDER BY decided_at DESC,adoption_id"
        with self._connect() as db:
            return [adoption_from_row(row) for row in db.execute(sql, params)]
