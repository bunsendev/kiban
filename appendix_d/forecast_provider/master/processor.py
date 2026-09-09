"""JAN名寄せ候補をHTTP外で生成する。"""

from .candidates import generate_candidates
from .contracts import MatchingJob


class MatchingProcessor:
    def __init__(self, store) -> None:
        self.store = store

    def process_next(self) -> MatchingJob | None:
        job = self.store.claim()
        if job is None:
            return None
        try:
            rows = self.store.source_rows(job)
            self.store.complete(job.matching_job_id, generate_candidates(job, rows))
        except Exception as exc:
            self.store.fail(job.matching_job_id, str(exc))
        return self.store.get_job(job.matching_job_id)
