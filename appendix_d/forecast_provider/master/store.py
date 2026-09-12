"""JAN名寄せ・商品masterのSQLite台帳。"""

import json
import sqlite3
from pathlib import Path

from .contracts import (
    CanonicalProduct,
    HandlingPeriod,
    JanMapping,
    MatchingCandidate,
    MatchingDecision,
    MatchingJob,
)
from .domain import periods_overlap


class SqliteMasterStore:
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

    def put_job(self, value: MatchingJob) -> MatchingJob:
        self._validate_normalizations(value.definition["normalization_ids"])
        definition = _json(value.definition)
        with self._connect() as db:
            db.execute(
                "INSERT INTO matching_jobs(matching_job_id,format_version,condition_fingerprint,"
                "definition_json,status,error) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (
                    value.matching_job_id,
                    value.format_version,
                    value.condition_fingerprint,
                    definition,
                    value.status,
                    value.error,
                ),
            )
        return self.get_job(value.matching_job_id)

    def _validate_normalizations(self, normalization_ids):
        with self._connect() as db:
            for normalization_id in normalization_ids:
                row = db.execute(
                    "SELECT n.status AS normalization_status,n.source_file_id,"
                    "s.status AS source_status,s.logical_path "
                    "FROM normalization_jobs n JOIN source_files s "
                    "ON s.source_file_id=n.source_file_id WHERE n.normalization_id=?",
                    (normalization_id,),
                ).fetchone()
                if row is None or row["normalization_status"] != "SUCCEEDED":
                    raise ValueError("成功済みnormalizationだけを指定できます")
                latest = db.execute(
                    "SELECT source_file_id FROM source_file_selections WHERE logical_path=? "
                    "ORDER BY decided_at DESC,selection_id DESC LIMIT 1",
                    (row["logical_path"],),
                ).fetchone()
                if latest is not None and latest[0] != row["source_file_id"]:
                    raise ValueError("現在採用中ではない原本のnormalizationです")

    def get_job(self, matching_job_id: str) -> MatchingJob | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM matching_jobs WHERE matching_job_id=?", (matching_job_id,)
            ).fetchone()
            return None if row is None else _job(row)

    def list_jobs(self) -> list[MatchingJob]:
        with self._connect() as db:
            return [
                _job(row)
                for row in db.execute(
                    "SELECT * FROM matching_jobs ORDER BY created_at DESC,matching_job_id DESC"
                )
            ]

    def claim(self) -> MatchingJob | None:
        job_id = None
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT matching_job_id FROM matching_jobs WHERE status='QUEUED' "
                "ORDER BY created_at,matching_job_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            job_id = row[0]
            db.execute(
                "UPDATE matching_jobs SET status='RUNNING' "
                "WHERE matching_job_id=? AND status='QUEUED'",
                (job_id,),
            )
        return self.get_job(job_id)

    def source_rows(self, job: MatchingJob) -> list[dict]:
        ids = job.definition["normalization_ids"]
        self._validate_normalizations(ids)
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT normalization_id,source_file_id,row_number,center_id,shipment_date,"
                    "raw_jan,raw_product_name,quantity,unit FROM shipment_rows "
                    f"WHERE status='ACCEPTED' AND normalization_id IN ({placeholders}) "
                    "ORDER BY normalization_id,row_number",
                    ids,
                )
            ]

    def complete(self, job_id: str, candidates: list[MatchingCandidate]):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "INSERT INTO matching_candidates VALUES (?,?,?,?,?)",
                [
                    (
                        value.candidate_id,
                        value.matching_job_id,
                        value.left_jan,
                        value.right_jan,
                        _json(value.details),
                    )
                    for value in candidates
                ],
            )
            db.execute(
                "UPDATE matching_jobs SET status='SUCCEEDED' WHERE matching_job_id=?", (job_id,)
            )

    def fail(self, job_id: str, error: str):
        with self._connect() as db:
            db.execute(
                "UPDATE matching_jobs SET status='FAILED',error=? WHERE matching_job_id=?",
                (error, job_id),
            )

    def list_candidates(self, job_id: str) -> list[MatchingCandidate]:
        with self._connect() as db:
            return [
                MatchingCandidate(
                    row["candidate_id"],
                    row["matching_job_id"],
                    row["left_jan"],
                    row["right_jan"],
                    json.loads(row["details_json"]),
                )
                for row in db.execute(
                    "SELECT * FROM matching_candidates WHERE matching_job_id=? "
                    "ORDER BY left_jan,right_jan",
                    (job_id,),
                )
            ]

    def put_product(self, value: CanonicalProduct):
        with self._connect() as db:
            db.execute(
                "INSERT INTO canonical_products VALUES (?,?,?,?,?)",
                (
                    value.canonical_product_id,
                    value.display_name,
                    value.created_by,
                    value.reason,
                    value.created_at,
                ),
            )

    def list_products(self) -> list[dict]:
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM canonical_products ORDER BY canonical_product_id"
                )
            ]

    def put_decision(self, value: MatchingDecision):
        with self._connect() as db:
            if (
                db.execute(
                    "SELECT 1 FROM matching_candidates WHERE candidate_id=?", (value.candidate_id,)
                ).fetchone()
                is None
            ):
                raise ValueError("候補が見つかりません")
            for product_id in (value.left_product_id, value.right_product_id):
                if (
                    product_id
                    and db.execute(
                        "SELECT 1 FROM canonical_products WHERE canonical_product_id=?",
                        (product_id,),
                    ).fetchone()
                    is None
                ):
                    raise ValueError("canonical productが見つかりません")
            if db.execute(
                "SELECT 1 FROM matching_decisions WHERE candidate_id=? AND mapping_version=?",
                (value.candidate_id, value.mapping_version),
            ).fetchone():
                raise ValueError("同じ候補とmapping versionの判断は変更できません")
            db.execute(
                "INSERT INTO matching_decisions VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    value.decision_id,
                    value.candidate_id,
                    value.decision,
                    value.left_product_id,
                    value.right_product_id,
                    value.mapping_version,
                    value.approved_by,
                    value.reason,
                    value.decided_at,
                ),
            )

    def list_decisions(self, candidate_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM matching_decisions"
        params = ()
        if candidate_id:
            sql += " WHERE candidate_id=?"
            params = (candidate_id,)
        sql += " ORDER BY decided_at,decision_id"
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, params)]

    def put_jan_mapping(self, value: JanMapping):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._put_jan_mapping(db, value)

    @staticmethod
    def _put_jan_mapping(db, value: JanMapping):
        _require_product(db, value.canonical_product_id)
        existing = db.execute(
            "SELECT valid_from,valid_to FROM jan_mappings WHERE jan=? AND mapping_version=?",
            (value.jan, value.mapping_version),
        )
        if any(
            periods_overlap(value.valid_from, value.valid_to, row[0], row[1]) for row in existing
        ):
            raise ValueError("同じJANとmapping versionの有効期間が競合します")
        db.execute(
            "INSERT INTO jan_mappings VALUES (?,?,?,?,?,?,?,?,?)",
            (
                value.jan_mapping_id,
                value.jan,
                value.canonical_product_id,
                value.valid_from,
                value.valid_to,
                value.mapping_version,
                value.approved_by,
                value.reason,
                value.decided_at,
            ),
        )

    def list_jan_mappings(self, mapping_version: str | None = None) -> list[dict]:
        return self._list_versioned("jan_mappings", "mapping_version", mapping_version)

    def put_handling_period(self, value: HandlingPeriod):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._put_handling_period(db, value)

    @staticmethod
    def _put_handling_period(db, value: HandlingPeriod):
        _require_product(db, value.canonical_product_id)
        existing = db.execute(
            "SELECT valid_from,valid_to FROM handling_periods WHERE canonical_product_id=? "
            "AND center_id=? AND period_version=?",
            (value.canonical_product_id, value.center_id, value.period_version),
        )
        if any(
            periods_overlap(value.valid_from, value.valid_to, row[0], row[1]) for row in existing
        ):
            raise ValueError("同じ商品・center・period versionの取扱期間が競合します")
        db.execute(
            "INSERT INTO handling_periods VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                value.handling_period_id,
                value.canonical_product_id,
                value.center_id,
                value.valid_from,
                value.valid_to,
                value.status,
                value.period_version,
                value.approved_by,
                value.basis,
                value.decided_at,
            ),
        )

    def list_handling_periods(self, period_version: str | None = None) -> list[dict]:
        return self._list_versioned("handling_periods", "period_version", period_version)

    def _list_versioned(self, table, version_column, version):
        sql = f"SELECT * FROM {table}"
        params = ()
        if version:
            sql += f" WHERE {version_column}=?"
            params = (version,)
        sql += " ORDER BY 1"
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, params)]


def _job(row):
    return MatchingJob(
        row["matching_job_id"],
        row["format_version"],
        row["condition_fingerprint"],
        json.loads(row["definition_json"]),
        row["status"],
        row["error"],
    )


def _require_product(db, product_id):
    if (
        db.execute(
            "SELECT 1 FROM canonical_products WHERE canonical_product_id=?", (product_id,)
        ).fetchone()
        is None
    ):
        raise ValueError("canonical productが見つかりません")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
