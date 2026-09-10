"""Provider適合記録と比較結果のBearer認証API。"""

from dataclasses import asdict

from fastapi import Depends, HTTPException

from ..errors import ContractViolationError
from ..evaluation_registry.service import EvaluationConflict, EvaluationNotFound
from .evaluation_schemas import ComparisonCreate, ConformanceCreate


def install_evaluation_routes(app, authorize, service) -> None:
    @app.post("/api/provider-conformance-tests", status_code=201)
    def create_conformance(request: ConformanceCreate, _auth: None = Depends(authorize)):
        try:
            return asdict(service.create_conformance(request.model_dump(mode="json")))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/provider-conformance-tests/{conformance_id}")
    def get_conformance(conformance_id: str, _auth: None = Depends(authorize)):
        try:
            return asdict(service.get_conformance(conformance_id))
        except EvaluationNotFound as exc:
            raise HTTPException(status_code=404, detail="適合記録が見つかりません") from exc

    @app.get("/api/provider-conformance-tests")
    def list_conformance(
        provider_id: str | None = None,
        model_id: str | None = None,
        _auth: None = Depends(authorize),
    ):
        return [asdict(value) for value in service.list_conformance(provider_id, model_id)]

    @app.get("/api/providers")
    def list_providers(_auth: None = Depends(authorize)):
        return service.list_providers()

    @app.post("/api/comparisons", status_code=201)
    def create_comparison(request: ComparisonCreate, _auth: None = Depends(authorize)):
        try:
            return service.comparison_detail(
                service.create_comparison(request.model_dump(mode="json")).comparison_id
            )
        except EvaluationNotFound as exc:
            raise HTTPException(status_code=404, detail="比較入力が見つかりません") from exc
        except (EvaluationConflict, ContractViolationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/comparisons/{comparison_id}")
    def get_comparison(comparison_id: str, _auth: None = Depends(authorize)):
        try:
            return service.comparison_detail(comparison_id)
        except EvaluationNotFound as exc:
            raise HTTPException(status_code=404, detail="比較結果が見つかりません") from exc

    @app.get("/api/comparisons")
    def list_comparisons(run_id: str | None = None, _auth: None = Depends(authorize)):
        return [asdict(value) for value in service.list_comparisons(run_id)]
