"""重要品目候補job・選定版の一覧読み取り。"""

from .contracts import CandidateJob, SelectionVersion
from .records import job_from_row, selection_from_row


class SelectionReadStoreMixin:
    """SQLite/PostgreSQLで共用する選定台帳の一覧処理。"""

    def list_candidate_jobs(self) -> list[CandidateJob]:
        with self._connect() as db:
            return [
                job_from_row(row)
                for row in db.execute(
                    "SELECT * FROM selection_candidate_jobs "
                    "ORDER BY created_at DESC,candidate_job_id"
                )
            ]

    def list_selections(self) -> list[SelectionVersion]:
        with self._connect() as db:
            return [
                selection_from_row(row)
                for row in db.execute(
                    "SELECT * FROM selections ORDER BY selected_at DESC,selection_id"
                )
            ]
