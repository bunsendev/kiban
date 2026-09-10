"""重要品目候補をHTTP外で算出して台帳へ保存する。"""

from decimal import Decimal

from .classification import build_candidates
from .contracts import CandidateJob
from .metrics import calculate_product_metrics


class SelectionProcessor:
    def __init__(self, store, daily) -> None:
        self.store = store
        self.daily = daily

    def process_next(self) -> CandidateJob | None:
        job = self.store.claim()
        if job is None:
            return None
        try:
            daily_build = self.daily.get_job(job.definition["daily_build_id"])
            if daily_build is None or daily_build.status != "SUCCEEDED":
                raise ValueError("成功済み日次buildが見つかりません")
            values = self.daily.list_values(daily_build.build_id)
            metrics = calculate_product_metrics(values)
            product_ids = {item.canonical_product_id for item in metrics}
            business_ids = set(job.definition["business_product_ids"])
            unknown = business_ids - product_ids
            if unknown:
                unknown_text = ", ".join(sorted(unknown))
                raise ValueError(f"業務指定品目が日次buildにありません: {unknown_text}")
            mappings = self.daily.list_jan_mappings(daily_build.definition["mapping_version"])
            jan_by_product = {}
            for mapping in mappings:
                product_jans = jan_by_product.setdefault(mapping["canonical_product_id"], set())
                product_jans.add(mapping["jan"])
            jan_changed = {
                product_id
                for product_id, jan_values in jan_by_product.items()
                if len(jan_values) > 1
            }
            candidates = build_candidates(
                job.candidate_job_id,
                metrics,
                jan_changed,
                business_ids,
                Decimal(str(job.definition["max_missing_rate"])),
                Decimal(str(job.definition["stable_cv_max"])),
                Decimal(str(job.definition["intermittent_zero_rate_min"])),
            )
            if not candidates:
                raise ValueError("日次buildに候補品目がありません")
            self.store.complete(job.candidate_job_id, candidates)
        except Exception as exc:
            self.store.fail(job.candidate_job_id, str(exc))
        return self.store.get_candidate_job(job.candidate_job_id)
