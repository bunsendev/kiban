"""重要品目候補と確定選定版のSQLite台帳。"""

import sqlite3
from pathlib import Path

from .contracts import CandidateJob, SelectionCandidate, SelectionItem, SelectionVersion
from .read_store import SelectionReadStoreMixin
from .records import (
    candidate_from_row,
    encode_json,
    item_from_row,
    job_from_row,
    selection_from_row,
)


class SqliteSelectionStore(SelectionReadStoreMixin):
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

    def put_candidate_job(self, value: CandidateJob) -> CandidateJob:
        with self._connect() as db:
            source = db.execute(
                "SELECT status FROM daily_build_jobs WHERE build_id=?",
                (value.definition["daily_build_id"],),
            ).fetchone()
            if source is None:
                raise KeyError(value.definition["daily_build_id"])
            if source["status"] != "SUCCEEDED":
                raise ValueError("成功済み日次buildだけを候補算出に使用できます")
            db.execute(
                "INSERT INTO selection_candidate_jobs VALUES (?,?,?,?,?,NULL,CURRENT_TIMESTAMP) "
                "ON CONFLICT DO NOTHING",
                (
                    value.candidate_job_id,
                    value.format_version,
                    value.condition_fingerprint,
                    encode_json(value.definition),
                    value.status,
                ),
            )
        current = self.get_candidate_job(value.candidate_job_id)
        if current is None or current.definition != value.definition:
            raise ValueError("同じcandidate_job_idの内容は変更できません")
        return current

    def get_candidate_job(self, candidate_job_id: str) -> CandidateJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM selection_candidate_jobs WHERE candidate_job_id=?",
                (candidate_job_id,),
            ).fetchone()
            return None if row is None else job_from_row(row)

    def claim(self) -> CandidateJob | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT candidate_job_id FROM selection_candidate_jobs WHERE status='QUEUED' "
                "ORDER BY created_at,candidate_job_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            candidate_job_id = row[0]
            db.execute(
                "UPDATE selection_candidate_jobs SET status='RUNNING' "
                "WHERE candidate_job_id=? AND status='QUEUED'",
                (candidate_job_id,),
            )
        return self.get_candidate_job(candidate_job_id)

    def complete(self, candidate_job_id: str, candidates: list[SelectionCandidate]) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "INSERT INTO selection_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        item.candidate_job_id,
                        item.canonical_product_id,
                        item.rank,
                        str(item.total_quantity),
                        _text(item.quantity_share),
                        _text(item.coefficient_of_variation),
                        _text(item.zero_rate),
                        _text(item.missing_rate),
                        item.usable_days,
                        item.handled_days,
                        int(item.jan_changed),
                        int(item.business_designated),
                        encode_json(list(item.center_ids)),
                        encode_json(list(item.tags)),
                        int(item.eligible),
                        item.ineligibility_reason,
                    )
                    for item in candidates
                ],
            )
            changed = db.execute(
                "UPDATE selection_candidate_jobs SET status='SUCCEEDED',error=NULL "
                "WHERE candidate_job_id=? AND status='RUNNING'",
                (candidate_job_id,),
            ).rowcount
            if changed != 1:
                raise ValueError("RUNNINGの候補算出jobだけを完了できます")

    def fail(self, candidate_job_id: str, error: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE selection_candidate_jobs SET status='FAILED',error=? "
                "WHERE candidate_job_id=? AND status='RUNNING'",
                (error, candidate_job_id),
            )

    def list_candidates(self, candidate_job_id: str) -> list[SelectionCandidate]:
        with self._connect() as db:
            return [
                candidate_from_row(row)
                for row in db.execute(
                    "SELECT * FROM selection_candidates WHERE candidate_job_id=? "
                    "ORDER BY rank,canonical_product_id",
                    (candidate_job_id,),
                )
            ]

    def put_selection(self, value: SelectionVersion) -> SelectionVersion:
        definition = value.definition
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM selections WHERE selection_version=?",
                (definition["selection_version"],),
            ).fetchone()
            if existing is not None:
                current = selection_from_row(existing)
                if current.selection_id != value.selection_id:
                    raise ValueError("同じselection_versionの内容は変更できません")
                return current
            job = db.execute(
                "SELECT status FROM selection_candidate_jobs WHERE candidate_job_id=?",
                (definition["candidate_job_id"],),
            ).fetchone()
            if job is None:
                raise KeyError(definition["candidate_job_id"])
            if job["status"] != "SUCCEEDED":
                raise ValueError("候補算出完了後に選定版を確定します")
            self._validate_items(db, value)
            db.execute(
                "INSERT INTO selections VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    value.selection_id,
                    value.format_version,
                    value.condition_fingerprint,
                    definition["selection_version"],
                    definition["candidate_job_id"],
                    definition["scope"],
                    encode_json(definition),
                    definition["selected_by"],
                    definition["rationale"],
                    value.selected_at,
                ),
            )
            db.executemany(
                "INSERT INTO selection_items VALUES (?,?,?,?)",
                [
                    (
                        value.selection_id,
                        item["canonical_product_id"],
                        encode_json(item["center_ids"]),
                        item["reason"],
                    )
                    for item in definition["items"]
                ],
            )
        saved = self.get_selection(value.selection_id)
        if saved is None:
            raise RuntimeError("保存した選定版を取得できません")
        return saved

    def _validate_items(self, db, value: SelectionVersion) -> None:
        job_id = value.definition["candidate_job_id"]
        for item in value.definition["items"]:
            row = db.execute(
                "SELECT * FROM selection_candidates "
                "WHERE candidate_job_id=? AND canonical_product_id=?",
                (job_id, item["canonical_product_id"]),
            ).fetchone()
            if row is None:
                raise ValueError("選定品目が候補算出結果にありません")
            candidate = candidate_from_row(row)
            if not candidate.eligible:
                raise ValueError("品質条件を満たさない候補は選定できません")
            if not set(item["center_ids"]).issubset(candidate.center_ids):
                raise ValueError("候補の対象外centerは選定できません")

    def get_selection(self, selection_id: str) -> SelectionVersion | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM selections WHERE selection_id=?", (selection_id,)
            ).fetchone()
            return None if row is None else selection_from_row(row)

    def list_selection_items(self, selection_id: str) -> list[SelectionItem]:
        with self._connect() as db:
            return [
                item_from_row(row)
                for row in db.execute(
                    "SELECT * FROM selection_items WHERE selection_id=? "
                    "ORDER BY canonical_product_id",
                    (selection_id,),
                )
            ]


def _text(value) -> str | None:
    return None if value is None else str(value)
