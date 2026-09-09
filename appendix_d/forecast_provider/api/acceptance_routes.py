"""少数実品目の受入case・技術判定・業務判断API。"""

from fastapi import Depends, FastAPI, HTTPException, status

from ..acceptance import make_acceptance_case, make_acceptance_decision
from .acceptance_schemas import AcceptanceCaseCreate, AcceptanceDecisionCreate
from .schemas import Created


def install_acceptance_routes(app: FastAPI, authorize, acceptance) -> None:
    @app.post(
        "/api/acceptance-cases",
        response_model=Created,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_case(request: AcceptanceCaseCreate, _auth: None = Depends(authorize)):
        try:
            value = make_acceptance_case(request.model_dump(mode="json"))
            acceptance.put_case(value)
            return Created(id=value.case_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/acceptance-cases/{case_id}")
    def get_case(case_id: str, _auth: None = Depends(authorize)):
        value = acceptance.get_case(case_id)
        if value is None:
            raise HTTPException(status_code=404, detail="受入caseが見つかりません")
        return value.__dict__

    @app.get("/api/acceptance-cases/{case_id}/checks")
    def get_checks(case_id: str, _auth: None = Depends(authorize)):
        if acceptance.get_case(case_id) is None:
            raise HTTPException(status_code=404, detail="受入caseが見つかりません")
        return [value.__dict__ for value in acceptance.list_checks(case_id)]

    @app.post(
        "/api/acceptance-cases/{case_id}/decisions",
        response_model=Created,
        status_code=201,
    )
    def create_decision(
        case_id: str,
        request: AcceptanceDecisionCreate,
        _auth: None = Depends(authorize),
    ):
        if acceptance.get_case(case_id) is None:
            raise HTTPException(status_code=404, detail="受入caseが見つかりません")
        try:
            value = make_acceptance_decision(case_id=case_id, **request.model_dump(mode="json"))
            acceptance.put_decision(value)
            return Created(id=value.decision_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/acceptance-cases/{case_id}/decisions")
    def get_decisions(case_id: str, _auth: None = Depends(authorize)):
        if acceptance.get_case(case_id) is None:
            raise HTTPException(status_code=404, detail="受入caseが見つかりません")
        return [value.__dict__ for value in acceptance.list_decisions(case_id)]
