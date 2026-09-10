"""Provider適合記録と比較結果のBearer認証API。"""

from dataclasses import asdict
from typing import Annotated

from fastapi import Depends, HTTPException

from ..errors import ContractViolationError
from ..evaluation_registry.service import EvaluationConflict, EvaluationNotFound
from .evaluation_schemas import ComparisonCreate, ConformanceCreate
from .security import Permission, Principal, audit_payload


def install_evaluation_routes(app, authorize, service) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)
    @app.post("/api/provider-conformance-tests", status_code=201)
    def create_conformance(
        request: ConformanceCreate,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return asdict(
                service.create_conformance(audit_payload(request, principal, "executed_by"))
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/provider-conformance-tests/{conformance_id}")
    def get_conformance(
        conformance_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            return asdict(service.get_conformance(conformance_id))
        except EvaluationNotFound as exc:
            raise HTTPException(status_code=404, detail="適合記録が見つかりません") from exc

    @app.get("/api/provider-conformance-tests")
    def list_conformance(
        _principal: Annotated[Principal, Depends(read)],
        provider_id: str | None = None,
        model_id: str | None = None,
    ):
        return [asdict(value) for value in service.list_conformance(provider_id, model_id)]

    @app.get("/api/providers")
    def list_providers(
        _principal: Annotated[Principal, Depends(read)],
    ):
        return service.list_providers()

    @app.post("/api/comparisons", status_code=201)
    def create_comparison(
        request: ComparisonCreate,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        try:
            return service.comparison_detail(
                service.create_comparison(
                    audit_payload(request, principal, "requested_by")
                ).comparison_id
            )
        except EvaluationNotFound as exc:
            raise HTTPException(status_code=404, detail="比較入力が見つかりません") from exc
        except (EvaluationConflict, ContractViolationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/comparisons/{comparison_id}")
    def get_comparison(
        comparison_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        try:
            return service.comparison_detail(comparison_id)
        except EvaluationNotFound as exc:
            raise HTTPException(status_code=404, detail="比較結果が見つかりません") from exc

    @app.get("/api/comparisons")
    def list_comparisons(
        _principal: Annotated[Principal, Depends(read)],
        run_id: str | None = None,
    ):
        return [asdict(value) for value in service.list_comparisons(run_id)]
