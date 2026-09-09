"""少数品目データ受入のSQLite台帳。"""

import sqlite3
from pathlib import Path

from .contracts import AcceptanceCase, AcceptanceCheck, AcceptanceDecision, ReportOutcome
from .records import case_from_row, check_from_row, decision_from_row, encode_json


class SqliteAcceptanceStore:
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

    def put_case(self, value: AcceptanceCase) -> AcceptanceCase:
        with self._connect() as db:
            db.execute(
                "INSERT INTO acceptance_cases("
                "case_id,format_version,condition_fingerprint,definition_json,status"
                ") VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                (
                    value.case_id,
                    value.format_version,
                    value.condition_fingerprint,
                    encode_json(value.definition),
                    value.status,
                ),
            )
        current = self.get_case(value.case_id)
        if current is None or current.definition != value.definition:
            raise ValueError("同じcase_idの内容は変更できません")
        return current

    def get_case(self, case_id: str) -> AcceptanceCase | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM acceptance_cases WHERE case_id=?", (case_id,)
            ).fetchone()
            return None if row is None else case_from_row(row)

    def claim(self) -> AcceptanceCase | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT case_id FROM acceptance_cases WHERE status='QUEUED' "
                "ORDER BY created_at,case_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            case_id = row[0]
            db.execute(
                "UPDATE acceptance_cases SET status='RUNNING' "
                "WHERE case_id=? AND status='QUEUED'",
                (case_id,),
            )
        return self.get_case(case_id)

    def complete(
        self,
        case_id: str,
        checks: list[AcceptanceCheck],
        outcome: ReportOutcome,
        report_uri: str,
        report_sha256: str,
        markdown_uri: str,
        markdown_sha256: str,
    ) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "INSERT INTO acceptance_checks VALUES (?,?,?,?,?,?)",
                [
                    (
                        item.case_id,
                        item.check_id,
                        item.status,
                        encode_json(item.actual),
                        encode_json(item.expected),
                        item.detail,
                    )
                    for item in checks
                ],
            )
            changed = db.execute(
                "UPDATE acceptance_cases SET status='SUCCEEDED',outcome=?,report_uri=?,"
                "report_sha256=?,markdown_uri=?,markdown_sha256=?,error=NULL "
                "WHERE case_id=? AND status='RUNNING'",
                (
                    outcome,
                    report_uri,
                    report_sha256,
                    markdown_uri,
                    markdown_sha256,
                    case_id,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("RUNNINGの受入caseだけを完了できます")

    def fail(self, case_id: str, error: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE acceptance_cases SET status='FAILED',error=? "
                "WHERE case_id=? AND status='RUNNING'",
                (error, case_id),
            )

    def list_checks(self, case_id: str) -> list[AcceptanceCheck]:
        with self._connect() as db:
            return [
                check_from_row(row)
                for row in db.execute(
                    "SELECT * FROM acceptance_checks WHERE case_id=? ORDER BY check_id",
                    (case_id,),
                )
            ]

    def put_decision(self, value: AcceptanceDecision) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM acceptance_cases WHERE case_id=?", (value.case_id,)
            ).fetchone()
            if row is None:
                raise KeyError(value.case_id)
            case = case_from_row(row)
            if case.status != "SUCCEEDED":
                raise ValueError("技術判定完了後に業務判断を記録します")
            if value.decision == "APPROVED" and (
                case.outcome != "PASSED" or case.definition["data_kind"] != "REAL"
            ):
                raise ValueError("技術判定PASSEDの実データcaseだけを承認できます")
            changed = db.execute(
                "INSERT INTO acceptance_decisions VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(case_id,decision_version) DO NOTHING",
                (
                    value.decision_id,
                    value.case_id,
                    value.decision_version,
                    value.decision,
                    value.decided_by,
                    value.reason,
                    value.decided_at,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("同じdecision versionの判断は変更できません")

    def list_decisions(self, case_id: str) -> list[AcceptanceDecision]:
        with self._connect() as db:
            return [
                decision_from_row(row)
                for row in db.execute(
                    "SELECT * FROM acceptance_decisions WHERE case_id=? "
                    "ORDER BY decided_at,decision_id",
                    (case_id,),
                )
            ]
