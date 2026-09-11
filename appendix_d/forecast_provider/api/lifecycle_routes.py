"""Model lifecycleのBearer認証API。"""

from dataclasses import asdict
from typing import Annotated

from fastapi import Depends, HTTPException

from ..lifecycle import LifecycleConflict, LifecycleNotFound
from .lifecycle_schemas import (
    CycleComplete,
    CycleFail,
    LifecyclePlanCreate,
    PromoteInput,
    RollbackInput,
    TrialAssessmentCreate,
    TrialForecastCreate,
)
from .security import Permission, Principal


def install_lifecycle_routes(app, authorize, service, trials) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)
    approve = authorize.require(Permission.APPROVE)

    @app.post("/api/lifecycle-plans", status_code=201)
    def create_plan(
        request: LifecyclePlanCreate,
        principal: Annotated[Principal, Depends(approve)],
    ):
        payload = request.model_dump(mode="python")
        payload["created_by"] = principal.subject
        return _call(lambda: asdict(service.create_plan(payload)))

    @app.get("/api/lifecycle-plans")
    def list_plans(_principal: Annotated[Principal, Depends(read)]):
        return [asdict(value) for value in service.list_plans()]

    @app.get("/api/lifecycle-plans/{plan_id}")
    def get_plan(plan_id: str, _principal: Annotated[Principal, Depends(read)]):
        return _call(lambda: service.status(plan_id))

    @app.post("/api/lifecycle-schedule")
    def schedule(_principal: Annotated[Principal, Depends(analyze)]):
        return _call(lambda: {"cycle_ids": service.schedule()})

    @app.get("/api/lifecycle-plans/{plan_id}/cycles")
    def list_cycles(plan_id: str, _principal: Annotated[Principal, Depends(read)]):
        return _call(lambda: [asdict(value) for value in service.list_cycles(plan_id)])

    @app.post("/api/lifecycle-cycles/{cycle_id}/complete")
    def complete_cycle(
        cycle_id: str,
        request: CycleComplete,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        return _call(
            lambda: asdict(
                service.complete_cycle(
                    cycle_id, request.challenger_run_id, request.comparison_id
                )
            )
        )

    @app.post("/api/lifecycle-cycles/{cycle_id}/fail")
    def fail_cycle(
        cycle_id: str,
        request: CycleFail,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        return _call(lambda: asdict(service.fail_cycle(cycle_id, request.failure_code)))

    @app.post("/api/lifecycle-cycles/{cycle_id}/promote")
    def promote(
        cycle_id: str,
        request: PromoteInput,
        principal: Annotated[Principal, Depends(approve)],
    ):
        return _call(
            lambda: asdict(
                service.promote(
                    cycle_id, request.expected_revision, principal.subject, request.reason
                )
            )
        )

    @app.post("/api/lifecycle-plans/{plan_id}/rollback")
    def rollback(
        plan_id: str,
        request: RollbackInput,
        principal: Annotated[Principal, Depends(approve)],
    ):
        return _call(
            lambda: asdict(
                service.rollback(
                    plan_id,
                    request.target_run_id,
                    request.expected_revision,
                    principal.subject,
                    request.reason,
                )
            )
        )

    @app.post("/api/lifecycle-plans/{plan_id}/trial-forecasts", status_code=201)
    def record_trial_forecast(
        plan_id: str,
        request: TrialForecastCreate,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        return _call(
            lambda: asdict(
                trials.record_forecast(
                    plan_id, request.run_id, request.origin_date, principal.subject
                )
            )
        )

    @app.get("/api/lifecycle-plans/{plan_id}/trial-forecasts")
    def list_trial_forecasts(
        plan_id: str, _principal: Annotated[Principal, Depends(read)]
    ):
        return _call(lambda: [asdict(value) for value in trials.list_forecasts(plan_id)])

    @app.post("/api/lifecycle-plans/{plan_id}/trial-assessments", status_code=201)
    def assess_trial(
        plan_id: str,
        request: TrialAssessmentCreate,
        principal: Annotated[Principal, Depends(approve)],
    ):
        return _call(
            lambda: asdict(
                trials.assess(
                    plan_id,
                    request.expected_revision,
                    request.period_start,
                    request.period_end,
                    request.comparison_id,
                    request.decision,
                    principal.subject,
                    request.reason,
                )
            )
        )

    @app.get("/api/lifecycle-plans/{plan_id}/trial-assessments")
    def list_trial_assessments(
        plan_id: str, _principal: Annotated[Principal, Depends(read)]
    ):
        return _call(lambda: [asdict(value) for value in trials.list_assessments(plan_id)])


def _call(callback):
    try:
        return callback()
    except LifecycleNotFound as exc:
        raise HTTPException(status_code=404, detail="lifecycleの参照先が見つかりません") from exc
    except LifecycleConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

