"""Lifecycle台帳のtrial予測・評価操作。"""

from dataclasses import replace

from .contracts import TrialAssessment, TrialForecastRecord
from .errors import LifecycleStoreConflict
from .records import trial_assessment_from_row, trial_forecast_from_row


class TrialStoreMixin:
    def put_trial_forecast(self, value: TrialForecastRecord) -> TrialForecastRecord:
        with self._connect() as db:
            db.execute(
                "INSERT INTO trial_forecast_records VALUES (?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (
                    value.record_id,
                    value.plan_id,
                    value.run_id,
                    value.origin_date.isoformat(),
                    value.recorded_by,
                    value.recorded_at,
                ),
            )
            row = db.execute(
                "SELECT * FROM trial_forecast_records WHERE plan_id=? AND origin_date=?",
                (value.plan_id, value.origin_date.isoformat()),
            ).fetchone()
        current = None if row is None else trial_forecast_from_row(row)
        if current is None or replace(current, recorded_at=value.recorded_at) != value:
            raise LifecycleStoreConflict("同じtrial originの記録は変更できません")
        return current

    def list_trial_forecasts(self, plan_id: str) -> list[TrialForecastRecord]:
        with self._connect() as db:
            return [
                trial_forecast_from_row(row)
                for row in db.execute(
                    "SELECT * FROM trial_forecast_records WHERE plan_id=? "
                    "ORDER BY origin_date,record_id",
                    (plan_id,),
                )
            ]

    def append_trial_assessment(
        self, value: TrialAssessment, expected_revision: int
    ) -> TrialAssessment:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT MAX(revision) AS revision FROM trial_assessments WHERE plan_id=?",
                (value.plan_id,),
            ).fetchone()
            current = 0 if row is None or row["revision"] is None else int(row["revision"])
            if current != expected_revision or value.revision != current + 1:
                raise LifecycleStoreConflict("trial assessment revisionが更新されています")
            db.execute(
                "INSERT INTO trial_assessments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    value.assessment_id,
                    value.plan_id,
                    value.revision,
                    value.period_start.isoformat(),
                    value.period_end.isoformat(),
                    value.comparison_id,
                    value.evidence_kind,
                    value.decision,
                    value.assessed_by,
                    value.reason,
                    value.created_at,
                ),
            )
        return value

    def list_trial_assessments(self, plan_id: str) -> list[TrialAssessment]:
        with self._connect() as db:
            return [
                trial_assessment_from_row(row)
                for row in db.execute(
                    "SELECT * FROM trial_assessments WHERE plan_id=? "
                    "ORDER BY revision,assessment_id",
                    (plan_id,),
                )
            ]
