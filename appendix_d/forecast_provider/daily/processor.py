"""日次buildをHTTP外で実行しdataset snapshotへ接続する。"""

from datetime import date, datetime
from pathlib import Path

from ..catalog.domain import make_snapshot
from .aggregation import aggregate_shipments
from .calendar import known_closed_days
from .completeness import evaluate_completeness
from .contracts import DailyBuildJob
from .export import publish_daily_csv
from .snapshot import snapshot_manifest
from .states import decide_daily_values


class DailyProcessor:
    def __init__(self, store, catalog, output_root: Path) -> None:
        self.store = store
        self.catalog = catalog
        self.output_root = output_root

    def process_next(self) -> DailyBuildJob | None:
        job = self.store.claim()
        if job is None:
            return None
        try:
            definition = job.definition
            start = date.fromisoformat(definition["train_start"])
            end = date.fromisoformat(definition["test_end"])
            schedule = self.store.get_schedule(definition["schedule_id"])
            if schedule is None:
                raise ValueError("予定ファイル定義が見つかりません")
            sources = self.store.source_inputs(job)
            completeness = evaluate_completeness(
                job.build_id,
                schedule,
                sources,
                start,
                end,
                datetime.fromisoformat(definition["as_of"]),
                definition["availability_mode"],
            )
            aggregates = aggregate_shipments(
                sources,
                self.store.list_jan_mappings(definition["mapping_version"]),
                start,
                end,
                datetime.fromisoformat(definition["as_of"]),
            )
            values = decide_daily_values(
                job.build_id,
                definition["selected_series"],
                start,
                end,
                completeness,
                aggregates,
                self.store.list_handling_periods(definition["period_version"]),
                known_closed_days(
                    self.store.list_closed_days(definition["closure_version"]),
                    definition["as_of"],
                )
                if definition["closure_version"] is not None
                else [],
                definition["as_of"],
                definition["availability_mode"],
            )
            data_uri, data_sha256 = publish_daily_csv(values, self.output_root)
            snapshot = make_snapshot(snapshot_manifest(job, values, data_uri, data_sha256))
            self.catalog.put_snapshot(snapshot)
            self.store.complete(
                job.build_id,
                completeness,
                values,
                snapshot.snapshot_id,
                data_uri,
                data_sha256,
            )
        except Exception as exc:
            self.store.fail(job.build_id, str(exc))
        return self.store.get_job(job.build_id)
