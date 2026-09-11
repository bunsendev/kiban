"""Lifecycle recordの検証、内容ID、月次schedule計算。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .contracts import (
    ChampionEvent,
    LifecycleCycle,
    LifecyclePlan,
    TrialAssessment,
    TrialForecastRecord,
)

FORMAT_VERSION = 1
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def make_cycle(
    plan: LifecyclePlan,
    due_month: str,
    scheduled_for: datetime,
    *,
    now: datetime | None = None,
) -> LifecycleCycle:
    if not MONTH_PATTERN.fullmatch(due_month) or scheduled_for.tzinfo is None:
        raise ValueError("cycle scheduleが不正です")
    identity = _digest({"plan_id": plan.plan_id, "due_month": due_month})
    return LifecycleCycle(
        f"cycle-{identity}",
        plan.plan_id,
        due_month,
        scheduled_for.isoformat(),
        "QUEUED",
        None,
        None,
        None,
        None,
        _now(now).isoformat(),
        None,
    )


def make_champion_event(
    plan: LifecyclePlan,
    revision: int,
    action: str,
    from_run_id: str | None,
    to_run_id: str,
    cycle_id: str | None,
    comparison_id: str | None,
    approved_by: str,
    reason: str,
    *,
    now: datetime | None = None,
) -> ChampionEvent:
    if action not in {"INITIALIZED", "PROMOTED", "ROLLED_BACK"}:
        raise ValueError("champion actionが不正です")
    if isinstance(revision, bool) or revision < 1:
        raise ValueError("revisionは1以上です")
    _required(to_run_id=to_run_id, approved_by=approved_by, reason=reason)
    if action == "INITIALIZED" and (revision != 1 or from_run_id is not None):
        raise ValueError("初期化eventが不正です")
    if action == "PROMOTED" and (not cycle_id or not comparison_id or not from_run_id):
        raise ValueError("昇格eventにはcycle、比較、現championが必要です")
    if action == "ROLLED_BACK" and not from_run_id:
        raise ValueError("rollback eventには現championが必要です")
    created = _now(now).isoformat()
    definition = {
        "plan_id": plan.plan_id,
        "revision": revision,
        "action": action,
        "from_run_id": from_run_id,
        "to_run_id": to_run_id,
        "cycle_id": cycle_id,
        "comparison_id": comparison_id,
        "approved_by": approved_by,
        "reason": reason,
    }
    identifier = _digest(definition)
    return ChampionEvent(
        f"champion-event-{identifier}",
        plan.plan_id,
        revision,
        action,  # type: ignore[arg-type]
        from_run_id,
        to_run_id,
        cycle_id,
        comparison_id,
        approved_by,
        reason,
        created,
    )


def make_trial_forecast(
    plan: LifecyclePlan,
    run_id: str,
    origin_date: date,
    recorded_by: str,
    *,
    now: datetime | None = None,
) -> TrialForecastRecord:
    _required(run_id=run_id, recorded_by=recorded_by)
    origin = _date(origin_date, "origin_date")
    if not plan.trial_start_date <= origin <= plan.trial_end_date:
        raise ValueError("originがtrial期間外です")
    identifier = _digest(
        {"plan_id": plan.plan_id, "run_id": run_id, "origin_date": origin.isoformat()}
    )
    return TrialForecastRecord(
        f"trial-forecast-{identifier}",
        plan.plan_id,
        run_id,
        origin,
        recorded_by,
        _now(now).isoformat(),
    )


def make_trial_assessment(
    plan: LifecyclePlan,
    revision: int,
    period_start: date,
    period_end: date,
    comparison_id: str,
    decision: str,
    assessed_by: str,
    reason: str,
    *,
    now: datetime | None = None,
) -> TrialAssessment:
    start = _date(period_start, "period_start")
    end = _date(period_end, "period_end")
    if not plan.trial_start_date <= start <= end <= plan.trial_end_date:
        raise ValueError("評価期間がtrial期間外です")
    if (end - start).days + 1 < 30:
        raise ValueError("trial評価期間は30日以上です")
    if decision not in {"CONTINUE", "COMPLETE", "ROLLBACK"}:
        raise ValueError("trial decisionが不正です")
    _required(comparison_id=comparison_id, assessed_by=assessed_by, reason=reason)
    definition = {
        "plan_id": plan.plan_id,
        "revision": revision,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "comparison_id": comparison_id,
        "evidence_kind": "FUTURE_TRIAL",
        "decision": decision,
        "assessed_by": assessed_by,
        "reason": reason,
    }
    identifier = _digest(definition)
    return TrialAssessment(
        f"trial-assessment-{identifier}",
        plan.plan_id,
        revision,
        start,
        end,
        comparison_id,
        "FUTURE_TRIAL",
        decision,  # type: ignore[arg-type]
        assessed_by,
        reason,
        _now(now).isoformat(),
    )


def due_schedules(plan: LifecyclePlan, through: datetime) -> list[tuple[str, datetime]]:
    """trial期間内で期限到来した月次scheduleを返す。"""
    if through.tzinfo is None:
        raise ValueError("throughはtimezone付きです")
    zone = ZoneInfo(plan.timezone)
    local_through = through.astimezone(zone)
    hour, minute = _schedule_time(plan.schedule_time)
    cursor = plan.trial_start_date.replace(day=1)
    result = []
    while cursor <= min(plan.trial_end_date, local_through.date()):
        scheduled = datetime.combine(
            cursor.replace(day=plan.schedule_day), time(hour, minute), zone
        )
        if plan.trial_start_date <= scheduled.date() <= plan.trial_end_date:
            if scheduled <= local_through:
                result.append((cursor.strftime("%Y-%m"), scheduled))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result


def _schedule_time(value: object) -> tuple[int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("schedule_timeはHH:MMです")
    hour, minute = value.split(":")
    return int(hour), int(minute)


def _date(value: object, name: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(f"{name}はdateです")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}は数値です")
    result = float(value)
    if result != result or abs(result) == float("inf"):
        raise ValueError(f"{name}は有限値です")
    return result


def _required(**values) -> None:
    invalid = [name for name, value in values.items() if not isinstance(value, str) or not value]
    if invalid:
        raise ValueError(f"必須文字列が空です: {sorted(invalid)}")


def _now(value: datetime | None) -> datetime:
    result = datetime.now(UTC) if value is None else value
    if result.tzinfo is None:
        raise ValueError("時刻はtimezone付きです")
    return result.astimezone(UTC)


def _json_value(value):
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        )
    )


def _digest(value) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
