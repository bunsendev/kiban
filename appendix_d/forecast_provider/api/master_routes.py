"""JAN名寄せ・canonical product・取扱期間API route。"""

from fastapi import Depends, FastAPI, HTTPException, status

from ..master import (
    make_decision,
    make_handling_period,
    make_jan_mapping,
    make_matching_job,
    make_product,
)
from .schemas import (
    Created,
    DecisionCreate,
    HandlingPeriodCreate,
    JanMappingCreate,
    MatchingJobCreate,
    ProductCreate,
)


def install_master_routes(app: FastAPI, authorize, master) -> None:
    @app.post("/api/matching/jobs", response_model=Created, status_code=status.HTTP_202_ACCEPTED)
    def create_matching_job(request: MatchingJobCreate, _auth: None = Depends(authorize)):
        try:
            value = make_matching_job(request.model_dump())
            master.put_job(value)
            return Created(id=value.matching_job_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/matching/jobs/{matching_job_id}")
    def get_matching_job(matching_job_id: str, _auth: None = Depends(authorize)):
        value = master.get_job(matching_job_id)
        if value is None:
            raise HTTPException(status_code=404, detail="名寄せjobが見つかりません")
        return {
            **value.__dict__,
            "candidates": [item.__dict__ for item in master.list_candidates(matching_job_id)],
        }

    @app.get("/api/matching/candidates")
    def list_matching_candidates(matching_job_id: str, _auth: None = Depends(authorize)):
        if master.get_job(matching_job_id) is None:
            raise HTTPException(status_code=404, detail="名寄せjobが見つかりません")
        return [item.__dict__ for item in master.list_candidates(matching_job_id)]

    @app.post("/api/products", response_model=Created, status_code=201)
    def create_product(request: ProductCreate, _auth: None = Depends(authorize)):
        try:
            value = make_product(**request.model_dump())
            master.put_product(value)
            return Created(id=value.canonical_product_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/products")
    def list_products(_auth: None = Depends(authorize)):
        return master.list_products()

    @app.post("/api/matching/decisions", response_model=Created, status_code=201)
    def create_decision(request: DecisionCreate, _auth: None = Depends(authorize)):
        try:
            value = make_decision(**request.model_dump())
            master.put_decision(value)
            return Created(id=value.decision_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/matching/decisions")
    def list_decisions(candidate_id: str | None = None, _auth: None = Depends(authorize)):
        return master.list_decisions(candidate_id)

    @app.post("/api/jan-mappings", response_model=Created, status_code=201)
    def create_jan_mapping(request: JanMappingCreate, _auth: None = Depends(authorize)):
        try:
            payload = request.model_dump()
            payload["valid_from"] = request.valid_from.isoformat()
            payload["valid_to"] = None if request.valid_to is None else request.valid_to.isoformat()
            value = make_jan_mapping(**payload)
            master.put_jan_mapping(value)
            return Created(id=value.jan_mapping_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/jan-mappings")
    def list_jan_mappings(mapping_version: str | None = None, _auth: None = Depends(authorize)):
        return master.list_jan_mappings(mapping_version)

    @app.post("/api/handling-periods", response_model=Created, status_code=201)
    def create_handling_period(request: HandlingPeriodCreate, _auth: None = Depends(authorize)):
        try:
            payload = request.model_dump()
            payload["valid_from"] = request.valid_from.isoformat()
            payload["valid_to"] = None if request.valid_to is None else request.valid_to.isoformat()
            value = make_handling_period(**payload)
            master.put_handling_period(value)
            return Created(id=value.handling_period_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/handling-periods")
    def list_handling_periods(period_version: str | None = None, _auth: None = Depends(authorize)):
        return master.list_handling_periods(period_version)
