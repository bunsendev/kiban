"""日次buildからcatalog snapshot manifestを組み立てる。"""

from .contracts import DailyBuildJob, DailyValue


def snapshot_manifest(
    job: DailyBuildJob, values: list[DailyValue], data_uri: str, data_sha256: str
) -> dict:
    definition = job.definition
    unique_ids = sorted({item.unique_id for item in values})
    return {
        "data_uri": data_uri,
        "data_sha256": data_sha256,
        "feature_versions_uri": None,
        "feature_versions_sha256": None,
        "selection_version": definition["selection_version"],
        "unique_ids": unique_ids,
        "train_start": definition["train_start"],
        "train_end": definition["train_end"],
        "test_start": definition["test_start"],
        "test_end": definition["test_end"],
        "origin_interval_days": definition["origin_interval_days"],
        "max_horizon": definition["max_horizon"],
        "primary_horizon_max": definition["primary_horizon_max"],
        "report_horizons": definition["report_horizons"],
        "known_future_columns": [],
        "availability_mode": definition["availability_mode"],
        "provenance": {
            "daily_build_id": job.build_id,
            "schedule_id": definition["schedule_id"],
            "normalization_ids": definition["normalization_ids"],
            "mapping_version": definition["mapping_version"],
            "period_version": definition["period_version"],
            "closure_version": definition["closure_version"],
            "as_of": definition["as_of"],
        },
    }
