"""受入台帳の行と永続契約を変換する。"""

import json

from .contracts import AcceptanceCase, AcceptanceCheck, AcceptanceDecision


def encode_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def case_from_row(row) -> AcceptanceCase:
    return AcceptanceCase(
        row["case_id"],
        row["format_version"],
        row["condition_fingerprint"],
        json.loads(row["definition_json"]),
        row["status"],
        row["outcome"],
        row["report_uri"],
        row["report_sha256"],
        row["markdown_uri"],
        row["markdown_sha256"],
        row["error"],
    )


def check_from_row(row) -> AcceptanceCheck:
    return AcceptanceCheck(
        row["case_id"],
        row["check_id"],
        row["status"],
        json.loads(row["actual_json"]),
        json.loads(row["expected_json"]),
        row["detail"],
    )


def decision_from_row(row) -> AcceptanceDecision:
    return AcceptanceDecision(
        row["decision_id"],
        row["case_id"],
        row["decision_version"],
        row["decision"],
        row["decided_by"],
        row["reason"],
        row["decided_at"],
    )
