"""Provider適合記録と比較結果のSQLite台帳。"""

import sqlite3
from dataclasses import replace
from pathlib import Path

from .contracts import ComparisonRecord, ProviderConformance, RunEvaluation
from .records import (
    comparison_from_row,
    conformance_from_row,
    encode_json,
    evaluation_from_row,
)


class SqliteEvaluationRegistryStore:
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

    def put_conformance(self, value: ProviderConformance) -> ProviderConformance:
        with self._connect() as db:
            db.execute(
                "INSERT INTO provider_conformance_tests VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (
                    value.conformance_id,
                    value.format_version,
                    value.condition_fingerprint,
                    value.provider_id,
                    value.provider_version,
                    value.model_id,
                    value.library_name,
                    value.library_version,
                    value.test_suite_version,
                    encode_json(value.adapter_config),
                    encode_json(value.environment),
                    encode_json([item.__dict__ for item in value.checks]),
                    value.status,
                    int(value.fixed_ranking_eligible),
                    value.executed_by,
                    value.executed_at,
                    value.evidence_uri,
                    value.evidence_sha256,
                ),
            )
        current = self.get_conformance(value.conformance_id)
        if current != value:
            raise ValueError("同じconformance_idの内容は変更できません")
        return current

    def get_conformance(self, conformance_id: str) -> ProviderConformance | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM provider_conformance_tests WHERE conformance_id=?",
                (conformance_id,),
            ).fetchone()
            return None if row is None else conformance_from_row(row)

    def list_conformance(
        self, provider_id: str | None = None, model_id: str | None = None
    ) -> list[ProviderConformance]:
        clauses, params = [], []
        if provider_id is not None:
            clauses.append("provider_id=?")
            params.append(provider_id)
        if model_id is not None:
            clauses.append("model_id=?")
            params.append(model_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as db:
            return [
                conformance_from_row(row)
                for row in db.execute(
                    "SELECT * FROM provider_conformance_tests"
                    f"{where} ORDER BY executed_at DESC,conformance_id",
                    params,
                )
            ]

    def put_comparison(
        self, value: ComparisonRecord, scores: list[RunEvaluation]
    ) -> ComparisonRecord:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM comparison_reports WHERE comparison_id=?",
                (value.comparison_id,),
            ).fetchone()
            if existing is None:
                definition, result = value.definition, value.result
                db.execute(
                    "INSERT INTO comparison_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        value.comparison_id,
                        value.format_version,
                        value.condition_fingerprint,
                        encode_json(definition),
                        encode_json(result),
                        result["comparison_set_id"],
                        result["official_comparison_set_id"],
                        definition["truth_version"],
                        definition["evaluation_scope_hash"],
                        definition["mode"],
                        definition["horizon"],
                        int(result["ranking_ready"]),
                        int(result["official_ranking_ready"]),
                        value.created_at,
                    ),
                )
                db.executemany(
                    "INSERT INTO comparison_runs VALUES (?,?,?,?,?,?)",
                    [
                        (
                            item.comparison_id,
                            item.run_id,
                            item.provider_id,
                            item.model_name,
                            item.conformance_id,
                            encode_json(item.score),
                        )
                        for item in scores
                    ],
                )
            else:
                current = comparison_from_row(existing)
                if replace(current, created_at=value.created_at) != value:
                    raise ValueError("同じcomparison_idの内容は変更できません")
                saved_scores = self._evaluations(db, value.comparison_id)
                if saved_scores != sorted(scores, key=lambda item: item.run_id):
                    raise ValueError("同じcomparison_idのrun評価は変更できません")
        saved = self.get_comparison(value.comparison_id)
        if saved is None:
            raise RuntimeError("保存した比較結果を取得できません")
        return saved

    def get_comparison(self, comparison_id: str) -> ComparisonRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM comparison_reports WHERE comparison_id=?", (comparison_id,)
            ).fetchone()
            return None if row is None else comparison_from_row(row)

    def list_comparisons(self, run_id: str | None = None) -> list[ComparisonRecord]:
        sql = "SELECT c.* FROM comparison_reports c"
        params = ()
        if run_id is not None:
            sql += " JOIN comparison_runs r ON r.comparison_id=c.comparison_id WHERE r.run_id=?"
            params = (run_id,)
        sql += " ORDER BY c.created_at DESC,c.comparison_id"
        with self._connect() as db:
            return [comparison_from_row(row) for row in db.execute(sql, params)]

    def list_run_evaluations(self, comparison_id: str) -> list[RunEvaluation]:
        with self._connect() as db:
            return self._evaluations(db, comparison_id)

    @staticmethod
    def _evaluations(db, comparison_id: str) -> list[RunEvaluation]:
        return [
            evaluation_from_row(row)
            for row in db.execute(
                "SELECT * FROM comparison_runs WHERE comparison_id=? ORDER BY run_id",
                (comparison_id,),
            )
        ]
