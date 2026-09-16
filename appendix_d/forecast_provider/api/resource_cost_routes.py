"""資源計測参照と管理者向け単価登録API。"""

from dataclasses import asdict
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, HTTPException

from ..resource_cost import ResourceMetric, make_unit_price
from .resource_cost_schemas import UnitPriceCreate
from .security import Permission, Principal


def install_resource_cost_routes(app, authorize, store) -> None:
    read = authorize.require(Permission.READ)
    manage = authorize.require(Permission.MANAGE_RESOURCE)

    @app.get("/api/runs/{run_id}/resources")
    def get_run_resources(
        run_id: str,
        _principal: Annotated[Principal, Depends(read)],
    ):
        value = store.summarize(run_id, include_attempts=True)
        if value is None:
            raise HTTPException(status_code=404, detail="runが見つかりません")
        return value

    @app.post("/api/resource-unit-prices", status_code=201)
    def create_unit_price(
        request: UnitPriceCreate,
        principal: Annotated[Principal, Depends(manage)],
    ):
        value = request.model_dump()
        value["created_by"] = principal.subject
        try:
            price = make_unit_price(
                provider_id=value["provider_id"],
                metric=ResourceMetric(value["metric"]),
                unit_price=Decimal(str(value["unit_price"])),
                currency=value["currency"],
                retrieved_on=value["retrieved_on"],
                source_ref=value["source_ref"],
                created_by=value["created_by"],
            )
            return asdict(store.put_unit_price(price))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/resource-unit-prices")
    def list_unit_prices(
        _principal: Annotated[Principal, Depends(read)],
        provider_id: str | None = None,
        metric: ResourceMetric | None = None,
    ):
        return [asdict(value) for value in store.list_unit_prices(provider_id, metric)]
