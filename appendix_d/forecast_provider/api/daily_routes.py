"""予定ファイル・休業日・日次build API route。"""

from fastapi import Depends, FastAPI, HTTPException, status

from ..daily import make_closed_day, make_daily_build, make_file_schedule
from .daily_schemas import ClosedDayCreate, DailyBuildCreate, FileScheduleCreate
from .schemas import Created


def install_daily_routes(app: FastAPI, authorize, daily) -> None:
    @app.post("/api/file-schedules", response_model=Created, status_code=201)
    def create_file_schedule(request: FileScheduleCreate, _auth: None = Depends(authorize)):
        try:
            value = make_file_schedule(request.model_dump(mode="json"))
            daily.put_schedule(value)
            return Created(id=value.schedule_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/file-schedules/{schedule_id}")
    def get_file_schedule(schedule_id: str, _auth: None = Depends(authorize)):
        value = daily.get_schedule(schedule_id)
        if value is None:
            raise HTTPException(status_code=404, detail="予定ファイル定義が見つかりません")
        return value.__dict__

    @app.post("/api/closed-days", response_model=Created, status_code=201)
    def create_closed_day(request: ClosedDayCreate, _auth: None = Depends(authorize)):
        try:
            value = make_closed_day(**request.model_dump(mode="json"))
            daily.put_closed_day(value)
            return Created(id=value.closed_day_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/closed-days")
    def list_closed_days(closure_version: str | None = None, _auth: None = Depends(authorize)):
        return [value.__dict__ for value in daily.list_closed_days(closure_version)]

    @app.post("/api/daily-builds", response_model=Created, status_code=status.HTTP_202_ACCEPTED)
    def create_daily_build(request: DailyBuildCreate, _auth: None = Depends(authorize)):
        try:
            value = make_daily_build(request.model_dump(mode="json"))
            daily.put_job(value)
            return Created(id=value.build_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/daily-builds/{build_id}")
    def get_daily_build(build_id: str, _auth: None = Depends(authorize)):
        value = daily.get_job(build_id)
        if value is None:
            raise HTTPException(status_code=404, detail="日次buildが見つかりません")
        return value.__dict__

    @app.get("/api/daily-builds/{build_id}/completeness")
    def get_daily_completeness(build_id: str, _auth: None = Depends(authorize)):
        if daily.get_job(build_id) is None:
            raise HTTPException(status_code=404, detail="日次buildが見つかりません")
        return [value.__dict__ for value in daily.list_completeness(build_id)]

    @app.get("/api/daily-builds/{build_id}/values")
    def get_daily_values(build_id: str, _auth: None = Depends(authorize)):
        if daily.get_job(build_id) is None:
            raise HTTPException(status_code=404, detail="日次buildが見つかりません")
        return [value.__dict__ for value in daily.list_values(build_id)]
