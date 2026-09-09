"""受入caseをHTTP外で評価し、品質レポートを発行する。"""

from pathlib import Path

from .checks import evaluate_acceptance
from .contracts import AcceptanceCase
from .report import publish_report


class AcceptanceProcessor:
    def __init__(self, store, daily, catalog, output_root: Path) -> None:
        self.store = store
        self.daily = daily
        self.catalog = catalog
        self.output_root = output_root

    def process_next(self) -> AcceptanceCase | None:
        case = self.store.claim()
        if case is None:
            return None
        try:
            checks, summary, outcome = evaluate_acceptance(case, self.daily, self.catalog)
            report_uri, report_sha, markdown_uri, markdown_sha = publish_report(
                case, checks, summary, outcome, self.output_root
            )
            self.store.complete(
                case.case_id,
                checks,
                outcome,
                report_uri,
                report_sha,
                markdown_uri,
                markdown_sha,
            )
        except Exception as exc:
            self.store.fail(case.case_id, str(exc))
        return self.store.get_case(case.case_id)
