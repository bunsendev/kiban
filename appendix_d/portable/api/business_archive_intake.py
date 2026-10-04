"""Shared business ZIP intake used by HTTP upload and the drop folder."""

import os

from .business_archive import analyze_archive, atomic_json, content_id
from .business_review import apply_remembered_rules, latest_decisions, rebuild_reviewed_prepared


class BusinessArchiveIntake:
    def __init__(self, paths, daily_runs) -> None:
        self.paths = paths
        self.daily_runs = daily_runs

    def ingest(self, data: bytes) -> dict:
        analysis_id = content_id(data)
        prepared_path = self.paths.prepared / f"{analysis_id}.csv"
        report = analyze_archive(data, prepared_path)
        input_path = self.paths.input / f"{analysis_id}.zip"
        if not input_path.exists():
            temporary = input_path.with_suffix(".tmp")
            temporary.write_bytes(data)
            os.replace(temporary, input_path)
        report = {"analysis_id": analysis_id, "input_sha256": analysis_id, **report}
        atomic_json(self.paths.analysis / f"{analysis_id}.json", report)
        journal = self.paths.decisions / f"{analysis_id}.jsonl"
        apply_remembered_rules(report, journal, self.paths.decisions / "rules.jsonl")
        if latest_decisions(journal):
            rebuild_reviewed_prepared(
                prepared_path,
                self.paths.prepared / f"{analysis_id}-reviewed.csv",
                report,
                journal,
            )
        self.daily_runs.view(analysis_id)
        return report
