"""Shadow参考値の認証付き読み取りAPI。予測や出荷指示を保存しない。"""

from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, Field

from ..expiry_simulation import ExpirySimulationBlocked
from ..warehouse_projection import ProjectionBlocked
from .error_responses import error_response
from .security import Permission, Principal


class FieldShadowPreviewRequest(BaseModel):
    calculation_at: datetime
    pilot_scope_version: str = Field(min_length=1, max_length=160)
    identity_bridge_version: str = Field(min_length=1, max_length=160)
    forecast_run_id: str = Field(min_length=1, max_length=160)
    minimum_remaining_days: int = Field(ge=0, le=365)
    attention_days: int = Field(ge=0, le=365)
    policy_confirmed_by: str = Field(min_length=1, max_length=160)
    policy_reason: str = Field(min_length=1, max_length=500)
    policy_confirmed_at: datetime


def install_field_shadow_routes(app: FastAPI, authorize, service) -> None:
    read = authorize.require(Permission.READ)

    @app.post("/api/field-shadow/preview")
    def preview(
        payload: FieldShadowPreviewRequest,
        request: Request,
        _principal: Annotated[Principal, Depends(read)],
    ):
        request.state.audit_operation = "FIELD_SHADOW_PREVIEW_READ"
        try:
            return service.preview(**payload.model_dump())
        except (ProjectionBlocked, ExpirySimulationBlocked) as exc:
            return error_response(request, 422, "計算条件を確認してください", code=exc.code)
        except ValueError:
            return error_response(
                request, 422, "計算条件を確認してください", code="FIELD_SHADOW_INPUT_INVALID"
            )
