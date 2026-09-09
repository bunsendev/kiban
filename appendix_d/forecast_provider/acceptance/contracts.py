"""少数実品目の受入case、技術チェック、業務判断の永続契約。"""

from dataclasses import dataclass
from typing import Literal, Protocol

CheckStatus = Literal["PASSED", "FAILED", "NOT_EVALUATED"]
ReportOutcome = Literal["PASSED", "FAILED", "DRY_RUN"]
DataKind = Literal["REAL", "ANONYMIZED"]


@dataclass(frozen=True)
class AcceptanceCase:
    case_id: str
    format_version: int
    condition_fingerprint: str
    definition: dict
    status: str
    outcome: ReportOutcome | None = None
    report_uri: str | None = None
    report_sha256: str | None = None
    markdown_uri: str | None = None
    markdown_sha256: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class AcceptanceCheck:
    case_id: str
    check_id: str
    status: CheckStatus
    actual: dict
    expected: dict
    detail: str


@dataclass(frozen=True)
class AcceptanceDecision:
    decision_id: str
    case_id: str
    decision_version: str
    decision: Literal["APPROVED", "REJECTED"]
    decided_by: str
    reason: str
    decided_at: str


class AcceptanceStore(Protocol):
    def put_case(self, value: AcceptanceCase) -> AcceptanceCase: ...
    def get_case(self, case_id: str) -> AcceptanceCase | None: ...
    def claim(self) -> AcceptanceCase | None: ...
    def complete(
        self,
        case_id: str,
        checks: list[AcceptanceCheck],
        outcome: ReportOutcome,
        report_uri: str,
        report_sha256: str,
        markdown_uri: str,
        markdown_sha256: str,
    ) -> None: ...
    def fail(self, case_id: str, error: str) -> None: ...
    def list_checks(self, case_id: str) -> list[AcceptanceCheck]: ...
    def put_decision(self, value: AcceptanceDecision) -> None: ...
    def list_decisions(self, case_id: str) -> list[AcceptanceDecision]: ...
