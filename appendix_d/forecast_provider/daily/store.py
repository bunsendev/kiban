"""予定完全性・日次状態・dataset buildのSQLite台帳。"""

import sqlite3
from pathlib import Path

from .contracts import ClosedDay, DailyBuildJob, DailyValue, FileCompleteness, FileSchedule
from .records import (
    completeness_from_row,
    daily_value_from_row,
    decimal_text,
    encode_json,
    job_from_row,
    schedule_from_row,
)
from .upstream import source_inputs, validate_job_inputs


class SqliteDailyStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    def put_schedule(self, value: FileSchedule) -> None:
        encoded = encode_json(value.definition)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO file_schedules VALUES (?,?,?,?,1) ON CONFLICT DO NOTHING",
                (value.schedule_id, value.format_version, value.content_hash, encoded),
            )
            row = db.execute(
                "SELECT * FROM file_schedules WHERE schedule_id=?", (value.schedule_id,)
            ).fetchone()
            if schedule_from_row(row) != value:
                raise ValueError("同じschedule_idの内容は変更できません")
            existing = db.execute(
                "SELECT COUNT(*) FROM planned_files WHERE schedule_id=?", (value.schedule_id,)
            ).fetchone()[0]
            if existing == 0:
                db.executemany(
                    "INSERT INTO planned_files VALUES (?,?,?,?,?,?,?)",
                    [
                        (
                            value.schedule_id,
                            item["logical_path"],
                            item["center_id"],
                            item["file_type"],
                            item["target_start"],
                            item["target_end"],
                            int(item["absence_means_zero"]),
                        )
                        for item in value.definition["files"]
                    ],
                )

    def get_schedule(self, schedule_id: str) -> FileSchedule | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM file_schedules WHERE schedule_id=?", (schedule_id,)
            ).fetchone()
            return None if row is None else schedule_from_row(row)

    def put_closed_day(self, value: ClosedDay) -> None:
        with self._connect() as db:
            changed = db.execute(
                "INSERT INTO closed_days("
                "closed_day_id,center_id,closed_date,closure_version,available_at,"
                "approved_by,reason,decided_at"
                ") VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(center_id,closed_date,closure_version) DO NOTHING",
                (
                    value.closed_day_id,
                    value.center_id,
                    value.closed_date,
                    value.closure_version,
                    value.available_at,
                    value.approved_by,
                    value.reason,
                    value.decided_at,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("同じcenter・日付・closure versionは変更できません")

    def list_closed_days(self, closure_version: str | None = None) -> list[ClosedDay]:
        sql = "SELECT * FROM closed_days"
        params = ()
        if closure_version is not None:
            sql += " WHERE closure_version=?"
            params = (closure_version,)
        sql += " ORDER BY center_id,closed_date,closed_day_id"
        with self._connect() as db:
            return [ClosedDay(**dict(row)) for row in db.execute(sql, params)]

    def put_job(self, value: DailyBuildJob) -> DailyBuildJob:
        validate_job_inputs(self, value)
        with self._connect() as db:
            db.execute(
                "INSERT INTO daily_build_jobs("
                "build_id,format_version,condition_fingerprint,definition_json,status"
                ") VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                (
                    value.build_id,
                    value.format_version,
                    value.condition_fingerprint,
                    encode_json(value.definition),
                    value.status,
                ),
            )
        current = self.get_job(value.build_id)
        if current is None or current.definition != value.definition:
            raise ValueError("同じbuild_idの内容は変更できません")
        return current

    def get_job(self, build_id: str) -> DailyBuildJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM daily_build_jobs WHERE build_id=?", (build_id,)
            ).fetchone()
            return None if row is None else job_from_row(row)

    def claim(self) -> DailyBuildJob | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT build_id FROM daily_build_jobs WHERE status='QUEUED' "
                "ORDER BY created_at,build_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            build_id = row[0]
            db.execute(
                "UPDATE daily_build_jobs SET status='RUNNING' WHERE build_id=? AND status='QUEUED'",
                (build_id,),
            )
        return self.get_job(build_id)

    def source_inputs(self, job: DailyBuildJob) -> list[dict]:
        return source_inputs(self, job)

    def list_jan_mappings(self, mapping_version: str) -> list[dict]:
        return self._list_rows(
            "SELECT * FROM jan_mappings WHERE mapping_version=? "
            "ORDER BY jan,valid_from,jan_mapping_id",
            (mapping_version,),
        )

    def list_handling_periods(self, period_version: str) -> list[dict]:
        return self._list_rows(
            "SELECT * FROM handling_periods WHERE period_version=? "
            "ORDER BY canonical_product_id,center_id,valid_from,handling_period_id",
            (period_version,),
        )

    def complete(
        self,
        build_id: str,
        completeness: list[FileCompleteness],
        values: list[DailyValue],
        snapshot_id: str,
        data_uri: str,
        data_sha256: str,
    ) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "INSERT INTO daily_file_completeness("
                "build_id,center_id,target_date,status,expected_count,valid_count,"
                "zero_confirmable,available_at,missing_paths_json,invalid_paths_json"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        item.build_id,
                        item.center_id,
                        item.target_date,
                        item.status,
                        item.expected_count,
                        item.valid_count,
                        int(item.zero_confirmable),
                        item.available_at,
                        encode_json(list(item.missing_paths)),
                        encode_json(list(item.invalid_paths)),
                    )
                    for item in completeness
                ],
            )
            db.executemany(
                "INSERT INTO daily_values VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        item.build_id,
                        item.canonical_product_id,
                        item.center_id,
                        item.ds,
                        item.unique_id,
                        decimal_text(item.raw_quantity),
                        decimal_text(item.y),
                        item.state,
                        item.available_at,
                        item.issue,
                    )
                    for item in values
                ],
            )
            changed = db.execute(
                "UPDATE daily_build_jobs SET status='SUCCEEDED',snapshot_id=?,data_uri=?,"
                "data_sha256=?,error=NULL WHERE build_id=? AND status='RUNNING'",
                (snapshot_id, data_uri, data_sha256, build_id),
            ).rowcount
            if changed != 1:
                raise ValueError("RUNNINGの日次buildだけを完了できます")

    def fail(self, build_id: str, error: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE daily_build_jobs SET status='FAILED',error=? "
                "WHERE build_id=? AND status='RUNNING'",
                (error, build_id),
            )

    def list_completeness(self, build_id: str) -> list[FileCompleteness]:
        with self._connect() as db:
            return [
                completeness_from_row(row)
                for row in db.execute(
                    "SELECT * FROM daily_file_completeness WHERE build_id=? "
                    "ORDER BY center_id,target_date",
                    (build_id,),
                )
            ]

    def list_values(self, build_id: str) -> list[DailyValue]:
        with self._connect() as db:
            return [
                daily_value_from_row(row)
                for row in db.execute(
                    "SELECT * FROM daily_values WHERE build_id=? ORDER BY unique_id,ds",
                    (build_id,),
                )
            ]

    def _list_rows(self, sql: str, params=()) -> list[dict]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, params)]
