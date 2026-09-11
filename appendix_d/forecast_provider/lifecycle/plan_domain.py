"""Lifecycle計画の検証と初期champion作成。"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import ChampionEvent, LifecyclePlan
from .domain import (
    FORMAT_VERSION,
    _date,
    _digest,
    _json_value,
    _now,
    _number,
    _required,
    _schedule_time,
    make_champion_event,
)


def make_plan(
    definition: dict,
    initial_champion_run_id: str,
    fallback_run_id: str,
    trial_period_days: int,
    *,
    now: datetime | None = None,
) -> tuple[LifecyclePlan, ChampionEvent]:
    required = {
        "plan_version",
        "adoption_id",
        "experiment_id",
        "schedule_day",
        "schedule_time",
        "timezone",
        "trial_start_date",
        "metric",
        "minimum_improvement_pct",
        "maximum_failure_rate",
        "created_by",
        "reason",
    }
    if set(definition) != required:
        raise ValueError("lifecycle plan定義の項目が契約と一致しません")
    _required(
        plan_version=definition["plan_version"],
        adoption_id=definition["adoption_id"],
        experiment_id=definition["experiment_id"],
        created_by=definition["created_by"],
        reason=definition["reason"],
        initial_champion_run_id=initial_champion_run_id,
        fallback_run_id=fallback_run_id,
    )
    if initial_champion_run_id == fallback_run_id:
        raise ValueError("championとfallbackは分けます")
    day = definition["schedule_day"]
    if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 28:
        raise ValueError("schedule_dayは1から28の整数です")
    _schedule_time(definition["schedule_time"])
    try:
        ZoneInfo(definition["timezone"])
    except (TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError("timezoneが不正です") from exc
    start = _date(definition["trial_start_date"], "trial_start_date")
    if isinstance(trial_period_days, bool) or not 30 <= trial_period_days <= 366:
        raise ValueError("trial periodは30から366日です")
    metric = definition["metric"]
    if metric != "wape_pct":
        raise ValueError("Phase 1Sの昇格metricはwape_pctです")
    improvement = _number(definition["minimum_improvement_pct"], "minimum improvement")
    failure = _number(definition["maximum_failure_rate"], "maximum failure rate")
    if not 0 <= improvement <= 100 or not 0 <= failure <= 1:
        raise ValueError("昇格基準が範囲外です")
    normalized = _json_value(
        {
            **definition,
            "trial_start_date": start.isoformat(),
            "initial_champion_run_id": initial_champion_run_id,
            "fallback_run_id": fallback_run_id,
            "trial_period_days": trial_period_days,
        }
    )
    fingerprint = _digest(normalized)
    created = _now(now)
    plan = LifecyclePlan(
        f"lifecycle-{fingerprint}",
        FORMAT_VERSION,
        fingerprint,
        normalized["plan_version"],
        normalized["adoption_id"],
        normalized["experiment_id"],
        initial_champion_run_id,
        fallback_run_id,
        day,
        normalized["schedule_time"],
        normalized["timezone"],
        start,
        start + timedelta(days=trial_period_days - 1),
        metric,
        improvement,
        failure,
        normalized["created_by"],
        normalized["reason"],
        created.isoformat(),
    )
    event = make_champion_event(
        plan,
        1,
        "INITIALIZED",
        None,
        initial_champion_run_id,
        None,
        None,
        plan.created_by,
        "採用判断からchampionを初期化",
        now=created,
    )
    return plan, event

