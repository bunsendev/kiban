"""Lifecycle台帳のJSON表現とDB行変換。"""

import json
from datetime import date

from .contracts import (
    ChampionEvent,
    LifecycleCycle,
    LifecyclePlan,
    TrialAssessment,
    TrialForecastRecord,
)


def encode_json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def plan_from_row(row) -> LifecyclePlan:
    return LifecyclePlan(
        row["plan_id"],
        int(row["format_version"]),
        row["condition_fingerprint"],
        row["plan_version"],
        row["adoption_id"],
        row["experiment_id"],
        row["initial_champion_run_id"],
        row["fallback_run_id"],
        int(row["schedule_day"]),
        row["schedule_time"],
        row["timezone"],
        date.fromisoformat(row["trial_start_date"]),
        date.fromisoformat(row["trial_end_date"]),
        row["metric"],
        float(row["minimum_improvement_pct"]),
        float(row["maximum_failure_rate"]),
        row["created_by"],
        row["reason"],
        row["created_at"],
    )


def cycle_from_row(row) -> LifecycleCycle:
    return LifecycleCycle(
        row["cycle_id"],
        row["plan_id"],
        row["due_month"],
        row["scheduled_for"],
        row["status"],
        row["challenger_run_id"],
        row["comparison_id"],
        None if row["score_json"] is None else json.loads(row["score_json"]),
        row["failure_code"],
        row["created_at"],
        row["completed_at"],
    )


def champion_event_from_row(row) -> ChampionEvent:
    return ChampionEvent(
        row["event_id"],
        row["plan_id"],
        int(row["revision"]),
        row["action"],
        row["from_run_id"],
        row["to_run_id"],
        row["cycle_id"],
        row["comparison_id"],
        row["approved_by"],
        row["reason"],
        row["created_at"],
    )


def trial_forecast_from_row(row) -> TrialForecastRecord:
    return TrialForecastRecord(
        row["record_id"],
        row["plan_id"],
        row["run_id"],
        date.fromisoformat(row["origin_date"]),
        row["recorded_by"],
        row["recorded_at"],
    )


def trial_assessment_from_row(row) -> TrialAssessment:
    return TrialAssessment(
        row["assessment_id"],
        row["plan_id"],
        int(row["revision"]),
        date.fromisoformat(row["period_start"]),
        date.fromisoformat(row["period_end"]),
        row["comparison_id"],
        row["evidence_kind"],
        row["decision"],
        row["assessed_by"],
        row["reason"],
        row["created_at"],
    )


def plan_values(value: LifecyclePlan) -> tuple:
    return (
        value.plan_id,
        value.format_version,
        value.condition_fingerprint,
        value.plan_version,
        value.adoption_id,
        value.experiment_id,
        value.initial_champion_run_id,
        value.fallback_run_id,
        value.schedule_day,
        value.schedule_time,
        value.timezone,
        value.trial_start_date.isoformat(),
        value.trial_end_date.isoformat(),
        value.metric,
        value.minimum_improvement_pct,
        value.maximum_failure_rate,
        value.created_by,
        value.reason,
        value.created_at,
    )


def cycle_values(value: LifecycleCycle) -> tuple:
    return (
        value.cycle_id,
        value.plan_id,
        value.due_month,
        value.scheduled_for,
        value.status,
        value.challenger_run_id,
        value.comparison_id,
        None if value.score is None else encode_json(value.score),
        value.failure_code,
        value.created_at,
        value.completed_at,
    )


def champion_event_values(value: ChampionEvent) -> tuple:
    return (
        value.event_id,
        value.plan_id,
        value.revision,
        value.action,
        value.from_run_id,
        value.to_run_id,
        value.cycle_id,
        value.comparison_id,
        value.approved_by,
        value.reason,
        value.created_at,
    )
