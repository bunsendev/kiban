"""mappingドライランjobをHTTP外で処理する。"""

from pathlib import Path

from .contracts import DEFAULT_LIMITS, DryRunLimits
from .report import publish_report
from .runner import collect_dry_run_for_mapping


class MappingDryRunProcessor:
    def __init__(self, jobs, mappings, input_root: Path, output_root: Path) -> None:
        self.jobs = jobs
        self.mappings = mappings
        self.input_root = input_root
        self.output_root = output_root

    def process_next(self) -> bool:
        job = self.jobs.claim()
        if job is None:
            return False
        try:
            mapping = self.mappings.get_mapping(job.mapping_id)
            if mapping is None:
                self.jobs.fail(job.job_id, "MAPPING_NOT_FOUND")
                return True
            limits = DryRunLimits(
                sample_rows=job.sample_rows,
                max_source_bytes=DEFAULT_LIMITS.max_source_bytes,
                max_mapping_bytes=DEFAULT_LIMITS.max_mapping_bytes,
            )
            payload = collect_dry_run_for_mapping(
                self.input_root, job.source_path, mapping, limits
            )
            _, checksum = publish_report(payload, self.output_root)
            self.jobs.complete(job.job_id, payload["dry_run_id"], payload["outcome"], checksum)
        except Exception:
            self.jobs.fail(job.job_id, "DRY_RUN_EXECUTION_FAILED")
        return True
